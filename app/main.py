"""Jawab's web server: the customer chat, the owner dashboard, their APIs and pages (spec 6, 7, 9).

    uv run uvicorn app.main:from_env --factory --host 0.0.0.0 --port 5000

`from_env()` reads the settings below from the environment; tests call `create_app()` with an
in-memory database and ScriptedClients instead.

- OPENAI_API_KEY: the model provider's key. Without it the app runs in dry run (free; every
  customer message escalates to the owner, and onboarding can't run).
- JAWAB_MODEL: the model (default gpt-6-luna), or `dry-run`.
- DATABASE_URL: a Postgres URL for data that must last. Without it, a SQLite file (jawab.db),
  which on a free host vanishes on every restart: fine for the public demo, which resets itself.
- PLUG_OWNER_KEY: the owner key of the seeded demo business (a long random string in production).
"""

import html
import json
import logging
import os
import secrets
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine

from app.db import init_db, make_engine, make_session_factory
from app.limits import RateLimiter
from app.services import conversations as convs
from app.services import onboarding, owner, sandbox
from app.services.businesses import BrainCache, get_business
from brain.llm import DryRunClient, LLMClient, make_client

STATIC = Path(__file__).resolve().parent / "static"
EMBED_SCRIPT = Path(__file__).resolve().parent / "embed.js"  # a template, so it isn't under static/

MAX_MESSAGE_CHARS = 500
MAX_OWNER_TEXT_CHARS = 1000
MAX_BUSINESS_NAME_CHARS = 80
MAX_PASTED_CHARS = 20000  # a long price list or a website's text
MAX_INTERVIEW_REPLY_CHARS = 2000
MAX_KB_CHARS = 100000
DRAFT_MAX_TOKENS = 32000  # spec section 8: a whole KB is long
# Spending protection for the public demo (a provider spending cap is the last line of defence).
# Every model call counts: chat messages, owner answers, onboarding turns. Overridable by env var.
LIMIT_PER_VISITOR_PER_HOUR = 40
LIMIT_PER_DAY = 1500
ONBOARDINGS_PER_VISITOR_PER_DAY = 3  # an onboarding is several model calls, one of them long
ONBOARDINGS_PER_DAY = 30
SANDBOXES_PER_VISITOR_PER_DAY = 30  # no model call; shared networks share an address
SANDBOXES_PER_DAY = 400
DAY = 24 * 3600
DEFAULT_DATABASE_URL = "sqlite:///jawab.db"
MODEL = "gpt-6-luna"

log = logging.getLogger("jawab")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class OwnerText(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=MAX_OWNER_TEXT_CHARS)


class LearnEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    visibility: Literal["public", "internal"]
    text: str = Field(min_length=1, max_length=4000)


class LearnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["saved", "edited", "once"]
    entry: LearnEntry | None = None


class OnboardingStart(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    business_name: str = Field(min_length=1, max_length=MAX_BUSINESS_NAME_CHARS)
    mode: Literal["quick", "full"]
    pasted_text: str | None = Field(None, max_length=MAX_PASTED_CHARS)


class OnboardingReply(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=MAX_INTERVIEW_REPLY_CHARS)


class OnboardingKB(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_markdown: str = Field(min_length=1, max_length=MAX_KB_CHARS)


def not_found_page() -> HTMLResponse:
    """The styled 404 page, e.g. for a demo shop that went with a reset."""
    return HTMLResponse((STATIC / "notfound.html").read_text(encoding="utf-8"), status_code=404)


def visitor_id(request: Request) -> str:
    """Who a request is from, for the rate limits. Behind the host's proxy every request comes from
    the proxy, so the visitor's address comes from a header. Cloudflare (in front of Render) sets
    CF-Connecting-IP itself, so a visitor can't fake it; X-Forwarded-For's first entry can be set by
    the visitor, so it's only the fallback. Either way the daily caps bound the total spend."""
    cloudflare = request.headers.get("cf-connecting-ip", "").strip()
    if cloudflare:
        return cloudflare
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else "unknown"


def create_app(engine: Engine, client: LLMClient, limiter: RateLimiter | None = None,
               draft_client: LLMClient | None = None, onboarding_limiter: RateLimiter | None = None,
               sandbox_limiter: RateLimiter | None = None) -> FastAPI:
    """Build the app. Creates missing tables and seeds missing businesses before serving.

    `draft_client` writes onboarding drafts (a whole KB, so a bigger token budget); defaults to `client`.
    `onboarding_limiter` counts new /start sessions and `sandbox_limiter` new sandboxes, on top of
    `limiter`, which counts every model call.
    """
    session_factory = make_session_factory(engine)
    draft_client = draft_client or client
    init_db(engine, session_factory)
    brains = BrainCache(client)

    app = FastAPI(title="Jawab", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(StarletteHTTPException)
    async def friendly_404(request: Request, exc: StarletteHTTPException):
        # Pages get a proper page; the API keeps its JSON errors.
        if exc.status_code == 404 and not request.url.path.startswith("/api/"):
            return not_found_page()
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.middleware("http")
    async def revalidate_pages(request: Request, call_next):
        # Pages and their files are small: always revalidate, so a new version shows up at once.
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    def business_or_404(session, slug: str):
        business = get_business(session, slug)
        if business is None:
            raise HTTPException(404, "Business not found.")
        return business

    # --- Pages ----------------------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/b/{slug}", include_in_schema=False)
    def chat_page(slug: str):
        with session_factory() as session:
            business = get_business(session, slug)
            if business is None:
                return not_found_page()
            name = business.name
        # Link previews (WhatsApp) don't run JavaScript, so the business's name goes into the HTML.
        page = (STATIC / "chat.html").read_text(encoding="utf-8")
        return HTMLResponse(page.replace("{{business_name}}", html.escape(name)))

    @app.get("/owner/{slug}", include_in_schema=False)
    def owner_page(slug: str):
        # The page holds nothing secret; every API call it makes checks the key.
        with session_factory() as session:
            if get_business(session, slug) is None:
                return not_found_page()
        return FileResponse(STATIC / "owner.html")

    @app.get("/start", include_in_schema=False)
    def start_page() -> FileResponse:
        return FileResponse(STATIC / "start.html")

    @app.get("/try", include_in_schema=False)
    def try_page() -> FileResponse:
        # The customer chat and the owner inbox of the visitor's own sandbox, side by side.
        return FileResponse(STATIC / "try.html")

    @app.get("/demo/the-plug", include_in_schema=False)
    def demo_site() -> FileResponse:
        # A stand-in shop website that carries the chat bubble, to show what customers would see.
        return FileResponse(STATIC / "demo-the-plug.html")

    @app.get("/embed.js", include_in_schema=False)
    def embed_script(request: Request, b: str = Query("", max_length=100)) -> Response:
        with session_factory() as session:
            found = bool(b) and get_business(session, b) is not None
        if not found:
            return Response("/* Jawab: no business at this address. Check the b= part of the script link. */",
                            status_code=404, media_type="text/javascript")
        script = (EMBED_SCRIPT.read_text(encoding="utf-8")
                  .replace('"__JAWAB_SLUG__"', json.dumps(b))
                  .replace('"__JAWAB_BASE__"', json.dumps(str(request.base_url).rstrip("/"))))
        return Response(script, media_type="text/javascript")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "model": client.model}  # "dry-run" means no model is being called

    # --- Customer API ---------------------------------------------------------------------------

    @app.get("/api/b/{slug}/public")
    def public_info(slug: str) -> dict:
        with session_factory() as session:
            business = business_or_404(session, slug)
            return {"name": business.name, "suggestions": list(business.suggestions or []),
                    "languages": brains.get_brain(business).kb.languages}

    @app.get("/api/public-stats/{slug}")
    def public_stats(slug: str) -> dict:
        """The landing page's live numbers. Only for the demo business, and only these three."""
        with session_factory() as session:
            business = business_or_404(session, slug)
            if owner.demo_seed(business) is None or business.sandbox_of:
                raise HTTPException(404, "Business not found.")
            stats = owner.stats(session, business)
        return {"messages_handled": stats["messages_this_week"],
                "answered_without_owner_pct": stats["answered_by_bot_pct"],
                "questions_learned": stats["questions_learned"]}

    # A plain `def`: brain.decide() waits on the model's API, and FastAPI runs plain functions in a
    # thread pool, so one slow call doesn't block other visitors.
    @app.post("/api/b/{slug}/chat")
    def chat(slug: str, body: ChatRequest, request: Request) -> dict:
        with session_factory() as session:
            business = business_or_404(session, slug)
            # Checked after validation, so only real messages count against the limits.
            if limiter and (refusal := limiter.check(visitor_id(request))):
                raise HTTPException(429, refusal)

            # Steps 1-2: the conversation and the customer's message, saved before the model runs.
            conversation = convs.find_or_create_conversation(session, business, body.conversation_id)
            customer_message = convs.add_message(session, business, conversation, "customer", body.message)

            # Step 3: a person has taken over, so the bot stays out of it.
            if conversation.state == convs.HUMAN_HANDOFF:
                session.commit()
                return {"conversation_id": str(conversation.id), "state": conversation.state,
                        "message": None, "panel": None}

            # Step 4: history from the database, then the brain (outside any open transaction).
            incoming = convs.build_incoming(session, business, conversation, customer_message)
            brain = brains.get_brain(business)
            session.commit()
            try:
                result = brain.decide(incoming)
            except Exception:
                # Provider errors propagate from the brain (D-025). Log the details, show a plain message.
                log.exception("brain.decide failed for business %s", business.slug)
                raise HTTPException(503, "The assistant is unavailable right now. Please try again in a minute.")

            # Steps 5-6: save the reply and update the state and the owner's inbox.
            session.refresh(conversation)  # the owner may have changed it meanwhile
            decision = result.decision
            bot_message = convs.record_decision(session, business, conversation, customer_message, decision)
            session.commit()

            # Step 7: only customer-safe fields leave the server.
            return {
                "conversation_id": str(conversation.id),
                "state": conversation.state,
                "message": {"id": bot_message.id, "role": "bot", "text": bot_message.text,
                            "action": bot_message.action},
                "panel": convs.panel_for(decision, brain.kb),
            }

    @app.get("/api/b/{slug}/conversations/{conversation_id}/messages")
    def messages(slug: str, conversation_id: uuid.UUID, after: int = Query(0, ge=0)) -> dict:
        with session_factory() as session:
            business = business_or_404(session, slug)
            conversation = convs.get_conversation(session, business, conversation_id)
            if conversation is None:
                raise HTTPException(404, "Conversation not found.")
            rows = convs.messages_after(session, business, conversation, after)
            return {
                "state": conversation.state,
                "messages": [convs.customer_view(m) for m in rows],
            }

    # --- Owner API ------------------------------------------------------------------------------

    def owner_access(slug: str, request: Request):
        """Every owner route: the business (404 if unknown) and its key, from the X-Owner-Key header
        or the `key` query parameter, compared in constant time (403 if wrong or missing)."""
        key = request.headers.get("x-owner-key") or request.query_params.get("key") or ""
        with session_factory() as session:
            business = business_or_404(session, slug)
            if not secrets.compare_digest(key.encode(), business.owner_key.encode()):
                raise HTTPException(403, "Wrong or missing owner key.")
            yield session, business

    def owner_errors(call):
        try:
            return call()
        except owner.NotFound as e:
            raise HTTPException(404, str(e))
        except owner.Conflict as e:
            raise HTTPException(409, str(e))

    @app.get("/api/owner/{slug}/escalations")
    def owner_escalations(access=Depends(owner_access)) -> dict:
        session, business = access
        return {"escalations": owner.list_escalations(session, business)}

    # Plain `def`s: the answer route waits on the model, which runs in FastAPI's thread pool.
    @app.post("/api/owner/{slug}/escalations/{escalation_id}/answer")
    def owner_answer(escalation_id: int, body: OwnerText, access=Depends(owner_access)) -> dict:
        session, business = access
        result = owner_errors(lambda: owner.answer_ask_owner(session, business, escalation_id, body.text, client))
        if result.outcome.fallback_used:
            log.warning("learn call fell back for escalation %s: %s", escalation_id, result.outcome.problems)
        return {"escalation": owner.escalation_view(session, business, result.escalation)}

    @app.post("/api/owner/{slug}/escalations/{escalation_id}/reply")
    def owner_reply(escalation_id: int, body: OwnerText, access=Depends(owner_access)) -> dict:
        session, business = access
        escalation = owner_errors(lambda: owner.reply_to_handoff(session, business, escalation_id, body.text))
        return {"escalation": owner.escalation_view(session, business, escalation)}

    @app.post("/api/owner/{slug}/escalations/{escalation_id}/give-back")
    def owner_give_back(escalation_id: int, access=Depends(owner_access)) -> dict:
        session, business = access
        escalation = owner_errors(lambda: owner.give_back_to_bot(session, business, escalation_id))
        return {"escalation": owner.escalation_view(session, business, escalation)}

    @app.post("/api/owner/{slug}/escalations/{escalation_id}/learn")
    def owner_learn(escalation_id: int, body: LearnRequest, access=Depends(owner_access)) -> dict:
        session, business = access
        if body.decision == "edited" and body.entry is None:
            raise HTTPException(422, "An edited entry needs an ID, a visibility and a text.")
        entry = body.entry.model_dump() if body.entry and body.decision == "edited" else None
        result = owner_errors(lambda: owner.apply_learning(session, business, escalation_id, body.decision, entry))
        if result.ok and result.entry_id:
            log.info("learned %s for %s from escalation %s", result.entry_id, business.slug, escalation_id)
        response = {"ok": result.ok}
        if result.error:
            response["error"] = result.error
        if result.entry_id:
            response["entry_id"] = result.entry_id
        return response

    @app.get("/api/owner/{slug}/stats")
    def owner_stats(access=Depends(owner_access)) -> dict:
        session, business = access
        return owner.stats(session, business)

    @app.post("/api/owner/{slug}/reset-demo")
    def owner_reset_demo(access=Depends(owner_access)) -> dict:
        session, business = access
        version = owner_errors(lambda: owner.reset_demo(session, business))
        log.info("reset the demo business %s (kb_version %s)", business.slug, version)
        return {"ok": True, "kb_version": version}

    @app.get("/api/owner/{slug}/knowledge")
    def owner_knowledge(access=Depends(owner_access)) -> dict:
        session, business = access
        return owner.knowledge(session, business)

    # --- Sandboxes: "Try it as the owner" ------------------------------------------------------

    @app.post("/api/sandbox")
    def create_sandbox(request: Request) -> dict:
        """A private copy of the demo business for this visitor: its chat and its owner inbox."""
        if sandbox_limiter and (refusal := sandbox_limiter.check(visitor_id(request))):
            if not refusal.startswith("The demo has reached"):
                refusal = "You've started over a lot today. Please come back tomorrow, or keep using your current demo."
            raise HTTPException(429, refusal)
        try:
            business, removed = sandbox.create(session_factory)
        except sandbox.Full as e:
            raise HTTPException(503, str(e))
        brains.forget(removed)
        return {"slug": business.slug, "owner_key": business.owner_key,
                "chat_url": f"/b/{business.slug}", "owner_url": f"/owner/{business.slug}?key={business.owner_key}"}

    # --- Onboarding API (spec section 8) -------------------------------------------------------
    # Public, so every route that calls the model counts against the same limits as the chat.

    def spend(request: Request) -> None:
        if limiter and (refusal := limiter.check(visitor_id(request))):
            raise HTTPException(429, refusal)

    def onboarding_errors(call):
        try:
            return call()
        except onboarding.NotFound as e:
            raise HTTPException(404, str(e))
        except onboarding.Conflict as e:
            raise HTTPException(409, str(e))
        except onboarding.ModelFailed as e:
            raise HTTPException(503, str(e))
        except onboarding.InvalidKB as e:
            raise HTTPException(422, "The knowledge base can't be published yet: " + "; ".join(e.problems))

    def links(request: Request, published: onboarding.Published) -> dict:
        base = str(request.base_url).rstrip("/")
        chat_url = f"{base}/b/{published.slug}"
        return {
            "slug": published.slug,
            "chat_url": chat_url,
            "owner_url": f"{base}/owner/{published.slug}?key={published.owner_key}",
            "embed_html": (f'<iframe src="{chat_url}" title="Chat" '
                           'style="width:100%;max-width:420px;height:640px;border:0;border-radius:16px"></iframe>'),
        }

    # Plain `def`s: they wait on the model, which runs in FastAPI's thread pool.
    @app.post("/api/onboarding")
    def onboarding_start(body: OnboardingStart, request: Request) -> dict:
        if onboarding_limiter and (refusal := onboarding_limiter.check(visitor_id(request))):
            if not refusal.startswith("The demo has reached"):
                refusal = f"You've set up {ONBOARDINGS_PER_VISITOR_PER_DAY} businesses today. Please come back tomorrow!"
            raise HTTPException(429, refusal)
        spend(request)
        return onboarding_errors(lambda: onboarding.start(
            session_factory, client, body.business_name, body.mode, body.pasted_text or None))

    @app.get("/api/onboarding/{session_id}")
    def onboarding_state(session_id: uuid.UUID, request: Request) -> dict:
        view, published = onboarding_errors(lambda: onboarding.state(session_factory, session_id))
        view["published"] = links(request, published) if published else None
        return view

    @app.post("/api/onboarding/{session_id}/reply")
    def onboarding_reply(session_id: uuid.UUID, body: OnboardingReply, request: Request) -> dict:
        onboarding_errors(lambda: onboarding.state(session_factory, session_id))  # 404 before counting
        spend(request)
        return onboarding_errors(lambda: onboarding.reply(session_factory, client, session_id, body.text))

    @app.post("/api/onboarding/{session_id}/draft")
    def onboarding_draft(session_id: uuid.UUID, request: Request) -> dict:
        onboarding_errors(lambda: onboarding.state(session_factory, session_id))
        spend(request)
        return onboarding_errors(lambda: onboarding.draft(session_factory, draft_client, session_id))

    @app.post("/api/onboarding/{session_id}/check")
    def onboarding_check(session_id: uuid.UUID, body: OnboardingKB) -> dict:
        """Not in the spec: re-checks the KB after "Edit raw", for the cards and the Publish button."""
        onboarding_errors(lambda: onboarding.state(session_factory, session_id))
        return onboarding.check(body.kb_markdown)

    @app.post("/api/onboarding/{session_id}/publish")
    def onboarding_publish(session_id: uuid.UUID, body: OnboardingKB, request: Request) -> dict:
        view, published = onboarding_errors(lambda: onboarding.state(session_factory, session_id))
        if published is None:
            spend(request)  # a repeat publish calls no model
        published = onboarding_errors(lambda: onboarding.publish(
            session_factory, client, session_id, body.kb_markdown))
        return links(request, published)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def choose_client(max_tokens: int = 16000, warn: bool = True) -> LLMClient:
    """The shared model client. Dry run (free, always escalates) without OPENAI_API_KEY or when
    JAWAB_MODEL=dry-run."""
    model = os.environ.get("JAWAB_MODEL", MODEL)
    if model == "dry-run":
        return DryRunClient()
    if model.startswith("gpt-") and not os.environ.get("OPENAI_API_KEY"):
        if not warn:
            return DryRunClient()
        banner = "!" * 72
        log.warning("\n%s\n%s\n%s", banner,
                    "  FALLING BACK TO DRY RUN: OPENAI_API_KEY is missing.\n"
                    "  No model will be called; every customer message will escalate to the owner.",
                    banner)
        return DryRunClient()
    # The SDK reads OPENAI_API_KEY (and OPENAI_BASE_URL, for a gateway) from the environment.
    return make_client(model, effort="medium", max_tokens=max_tokens)


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def from_env() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    url = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    client = choose_client()
    draft_client = choose_client(max_tokens=DRAFT_MAX_TOKENS, warn=False)
    log.info("model client: %s; database: %s", client.model, url.split("://")[0])
    limiter = RateLimiter(per_visitor=env_int("JAWAB_LIMIT_PER_HOUR", LIMIT_PER_VISITOR_PER_HOUR),
                          per_day=env_int("JAWAB_LIMIT_PER_DAY", LIMIT_PER_DAY))
    onboarding_limiter = RateLimiter(per_visitor=ONBOARDINGS_PER_VISITOR_PER_DAY,
                                     per_day=env_int("JAWAB_ONBOARDINGS_PER_DAY", ONBOARDINGS_PER_DAY), window=DAY)
    sandbox_limiter = RateLimiter(per_visitor=SANDBOXES_PER_VISITOR_PER_DAY, per_day=SANDBOXES_PER_DAY, window=DAY)
    return create_app(make_engine(url), client, limiter, draft_client, onboarding_limiter, sandbox_limiter)
