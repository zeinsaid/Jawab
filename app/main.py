"""Jawab's web server: the customer chat, the owner dashboard, their APIs and pages (spec 6, 7, 9).

    uv run uvicorn app.main:from_env --factory --host 0.0.0.0 --port 5000

`from_env()` reads the settings below from the environment; tests call `create_app()` with an
in-memory database and ScriptedClients instead.

- OPENAI_API_KEY: the model provider's key. Without it the app runs in dry run (free; every
  customer message escalates to the owner, and onboarding can't run).
- JAWAB_MODEL: the model (default gpt-6-luna), or `dry-run`.
- DATABASE_URL: a Postgres URL for data that must last. Without it, a SQLite file (jawab.db),
  which on a free host vanishes on every restart: fine for the public demo, which resets itself.
- PLUG_OWNER_KEY: the owner key of the seeded business The Plug (a long random string in production).
- JAWAB_MODE: `multi` (default: the public demo, with the landing page, sandboxes and onboarding)
  or `single`: one business only (JAWAB_BUSINESS), nothing else served, and DATABASE_URL required.
- JAWAB_DEPLOYMENT: this deployment's name in alert subjects, e.g. "Jawab demo".
- JAWAB_CORS_ORIGINS / JAWAB_CORS_ORIGIN_REGEX: websites whose pages may call the API (the bubble
  loader's /health ping), e.g. "https://theplug.cy".
- RESEND_API_KEY, JAWAB_EMAIL_FROM: sending email. OWNER_ALERT_EMAIL, SHOP_ALERT_EMAILS: who gets it.
"""

import html
import json
import logging
import os
import re
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.db import Escalation, init_db, make_engine, make_session_factory
from app.limits import RateLimiter
from app.services import alerts as alerting
from app.services import conversations as convs
from app.services import onboarding, owner, sandbox
from app.services import settings as biz_settings
from app.services.businesses import BrainCache, get_business
from app.services.mail import Mailer, NullMailer, ResendMailer
from app.services.theme import accent_style
from brain.llm import DryRunClient, LLMClient, make_client
from brain.schema import Action

STATIC = Path(__file__).resolve().parent / "static"
LOADER_SCRIPT = STATIC / "jawab.js"  # the bubble; /embed.js serves it with a business's defaults filled in

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
# A chat reply should never hang: one model call gives up after this, with one SDK retry. The
# onboarding draft (a whole KB) gets longer.
MODEL_TIMEOUT_SECONDS = 45
DRAFT_TIMEOUT_SECONDS = 300
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^\+?[0-9][0-9 ()./-]{5,23}$")  # then 7 to 15 digits: a WhatsApp or phone number
TRANSCRIPT_IN_ALERT = 12  # messages in a complaint or lead email

# Single-business mode serves none of the public demo: no landing page, sandboxes or onboarding,
# so nobody can create a business or spend the business's key on anything but its own chat.
DEMO_ONLY_PATHS = ("/try", "/start", "/demo/", "/api/sandbox", "/api/onboarding", "/api/public-stats",
                   "/static/index.html", "/static/landing.", "/static/start.", "/static/try.",
                   "/static/demo-the-plug.html", "/static/notfound.html")

log = logging.getLogger("jawab")


@dataclass
class Deployment:
    """What this server is: the public demo (multi) or one business's own chat (single)."""

    mode: Literal["multi", "single"] = "multi"
    business: str | None = None  # single mode: the one business's slug
    name: str = "Jawab"  # alert subjects: "Jawab demo", "Jawab – The Plug"
    cors_origins: list[str] = field(default_factory=list)
    cors_origin_regex: str | None = None

    @property
    def single(self) -> bool:
        return self.mode == "single"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    lang: Literal["en", "el", "ar"] | None = None  # the page's language, for Latin-script messages


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=254, pattern=EMAIL.pattern)


class ContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contact: str = Field(min_length=3, max_length=254)  # an email or a WhatsApp / phone number


def parse_contact(value: str) -> tuple[str, str] | None:
    """("email", address) or ("phone", number) from what the customer typed, or None."""
    value = " ".join(value.split())
    if EMAIL.match(value):
        return "email", value
    digits = sum(ch.isdigit() for ch in value)
    if PHONE.match(value) and 7 <= digits <= 15:
        return "phone", value
    return None


class OwnerText(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=MAX_OWNER_TEXT_CHARS)


class LearnEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    visibility: Literal["public", "internal"]
    text: str = Field(min_length=1, max_length=4000)


class EntryUpdate(BaseModel):
    """A direct edit from the Knowledge tab. `base_text` is the text the owner started from (D-015)."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    visibility: Literal["public", "internal"]
    text: str = Field(min_length=1, max_length=4000)
    base_text: str | None = Field(default=None, max_length=20000)


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


PLAIN_404 = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"robots\" "
             "content=\"noindex\"><title>Not found</title></head><body style=\"font-family:system-ui;"
             "padding:48px\"><h1>Not found</h1></body></html>")


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
               sandbox_limiter: RateLimiter | None = None, deployment: Deployment | None = None,
               mailer: Mailer | None = None, alert_config: alerting.AlertConfig | None = None) -> FastAPI:
    """Build the app. Creates missing tables and seeds missing businesses before serving.

    `draft_client` writes onboarding drafts (a whole KB, so a bigger token budget); defaults to `client`.
    `onboarding_limiter` counts new /start sessions and `sandbox_limiter` new sandboxes, on top of
    `limiter`, which counts every model call. `mailer` sends the alerts (none without one).
    """
    deployment = deployment or Deployment()
    session_factory = make_session_factory(engine)
    draft_client = draft_client or client
    init_db(engine, session_factory, deployment.business if deployment.single else None)
    brains = BrainCache(client)
    alerts = alerting.Alerts(mailer or NullMailer(), alert_config or alerting.AlertConfig(deployment.name),
                             session_factory)

    app = FastAPI(title="Jawab", docs_url=None, redoc_url=None, openapi_url=None)

    def not_found_page() -> HTMLResponse:
        """The styled 404 page, e.g. for a demo shop that went with a reset. Single-business mode
        gets a plain one: the styled page links to the public demo."""
        if deployment.single:
            return HTMLResponse(PLAIN_404, status_code=404)
        return HTMLResponse((STATIC / "notfound.html").read_text(encoding="utf-8"), status_code=404)

    @app.exception_handler(StarletteHTTPException)
    async def friendly_404(request: Request, exc: StarletteHTTPException):
        # Pages get a proper page; the API keeps its JSON errors.
        if exc.status_code == 404 and not request.url.path.startswith("/api/"):
            return not_found_page()
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.middleware("http")
    async def revalidate_pages(request: Request, call_next):
        path = request.url.path
        if deployment.single and (path == "/" or path.startswith(DEMO_ONLY_PATHS)):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return not_found_page()
        # Pages and their files are small: always revalidate, so a new version shows up at once.
        response = await call_next(request)
        if not path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    if deployment.cors_origins or deployment.cors_origin_regex:
        # The bubble loader runs on the business's own website and pings /health from there.
        app.add_middleware(CORSMiddleware, allow_origins=deployment.cors_origins,
                           allow_origin_regex=deployment.cors_origin_regex,
                           allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    def find_business(session, slug: str):
        """A business by slug; in single-business mode only that one exists."""
        if deployment.single and slug != deployment.business:
            return None
        return get_business(session, slug)

    def business_or_404(session, slug: str):
        business = find_business(session, slug)
        if business is None:
            raise HTTPException(404, "Business not found.")
        return business

    def base_url(request: Request) -> str:
        return str(request.base_url).rstrip("/")

    # --- Pages ----------------------------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/b/{slug}", include_in_schema=False)
    def chat_page(slug: str):
        with session_factory() as session:
            business = find_business(session, slug)
            if business is None:
                return not_found_page()
            name = biz_settings.display_name(business)
            accent = biz_settings.effective(business)["accent"]
        # Link previews (WhatsApp) don't run JavaScript, so the business's name goes into the HTML;
        # so does its accent colour, so the page never flashes Jawab's own colour first.
        page = (STATIC / "chat.html").read_text(encoding="utf-8")
        page = page.replace("{{business_name}}", html.escape(name))
        page = page.replace("<!--{{accent_style}}-->", accent_style(accent))
        if accent:
            page = page.replace('<meta name="theme-color" content="#0F766E">',
                                f'<meta name="theme-color" content="{accent}">')
        return HTMLResponse(page)

    @app.get("/owner/{slug}", include_in_schema=False)
    def owner_page(slug: str):
        # The page holds nothing secret; every API call it makes checks the key.
        with session_factory() as session:
            if find_business(session, slug) is None:
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

    @app.get("/jawab.js", include_in_schema=False)
    def loader_script() -> FileResponse:
        """The bubble loader as a website should host it itself: configured by data- attributes."""
        return FileResponse(LOADER_SCRIPT, media_type="text/javascript")

    @app.get("/embed.js", include_in_schema=False)
    def embed_script(request: Request, b: str = Query("", max_length=100)) -> Response:
        """The same loader, served from here with one business's defaults filled in, for the
        one-line snippet. It only appears once this server is awake; a self-hosted copy doesn't wait."""
        with session_factory() as session:
            business = find_business(session, b) if b else None
            if business is None:
                return Response("/* Jawab: no business at this address. Check the b= part of the script link. */",
                                status_code=404, media_type="text/javascript")
            settings = biz_settings.effective(business)
            kb = brains.get_brain(business).kb
            defaults = {"base": base_url(request), "business": b, "name": biz_settings.display_name(business),
                        "accent": settings["accent"], "offline": settings["offline_message"],
                        "languages": biz_settings.ui_languages(kb.metadata, kb.languages, settings["ui_languages"])}
        # json.dumps escapes quotes; "</" can't end a script block inside a .js file anyway.
        script = LOADER_SCRIPT.read_text(encoding="utf-8").replace(
            "/*__JAWAB_DEFAULTS__*/{}", json.dumps(defaults, ensure_ascii=False).replace("</", "<\\/"))
        return Response(script, media_type="text/javascript")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "model": client.model}  # "dry-run" means no model is being called

    # --- Customer API ---------------------------------------------------------------------------

    @app.get("/api/b/{slug}/public")
    def public_info(slug: str) -> dict:
        with session_factory() as session:
            business = business_or_404(session, slug)
            kb = brains.get_brain(business).kb
            settings = biz_settings.effective(business)
            return {"name": biz_settings.display_name(business), "suggestions": business.suggestions or [],
                    "languages": kb.languages,  # the reply languages
                    "ui_languages": biz_settings.ui_languages(kb.metadata, kb.languages, settings["ui_languages"]),
                    "accent": settings["accent"],
                    "offline_message": settings["offline_message"],
                    "email_capture": settings["email_customers"]}

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

    def transcript(session, business, conversation_id) -> list[tuple[str, str]]:
        who = {"customer": "Customer", "bot": "Assistant", "staff": "Team"}
        return [(who.get(m.role, m.role), m.text)
                for m in owner.recent_messages(session, business, conversation_id, TRANSCRIPT_IN_ALERT)]

    # A plain `def`: brain.decide() waits on the model's API, and FastAPI runs plain functions in a
    # thread pool, so one slow call doesn't block other visitors.
    @app.post("/api/b/{slug}/chat")
    def chat(slug: str, body: ChatRequest, request: Request, background: BackgroundTasks):
        with session_factory() as session:
            business = business_or_404(session, slug)
            # Checked after validation, so only real messages count against the limits.
            if limiter and (refusal := limiter.check(visitor_id(request))):
                raise HTTPException(429, refusal)
            settings = biz_settings.effective(business)

            # Steps 1-2: the conversation and the customer's message, saved before the model runs.
            conversation = convs.find_or_create_conversation(session, business, body.conversation_id)
            conversation.language = convs.detect_language(body.message, body.lang or conversation.language)
            customer_message = convs.add_message(session, business, conversation, "customer", body.message)

            # Step 3: a person has taken over (or the chat ended in abuse), so the bot stays out of it.
            if conversation.state in convs.QUIET:
                session.commit()
                return {"conversation_id": str(conversation.id), "state": conversation.state,
                        "message": None, "panel": None, "contacts": None, "ask_email": False,
                        "ask_contact": False}

            # Step 4: history from the database, then the brain (outside any open transaction).
            incoming = convs.build_incoming(session, business, conversation, customer_message)
            brain = brains.get_brain(business)
            session.commit()
            try:
                result = brain.decide(incoming)
            except Exception as error:
                # Provider errors propagate from the brain (D-025): no credit, a quota, a timeout,
                # the provider down. Log the details, show the business's offline message, and
                # tell the owner (at most every 6 hours).
                log.exception("brain.decide failed for business %s", business.slug)
                background.add_task(alerts.offline, alerting.classify(error), f"{type(error).__name__}: {error}"[:300])
                return JSONResponse({"detail": biz_settings.pick(settings["offline_message"], conversation.language),
                                     "offline": True}, status_code=503)

            # Steps 5-6: save the reply and update the state and the owner's inbox.
            session.refresh(conversation)  # the owner may have changed it meanwhile
            decision = result.decision
            bot_message, created = convs.record_decision(session, business, conversation, customer_message, decision,
                                                         handoffs=settings["handoffs"])
            session.commit()

            # One email per new event, sent after the response has gone out.
            if created is not None and settings["alerts"]:
                if decision.action is Action.ASK_OWNER:
                    background.add_task(alerts.ask_owner, business.name, created.question, conversation.language,
                                        customer_message.text, f"{base_url(request)}/owner/{business.slug}")
                elif decision.handoff_reason in convs.TEAM_REASONS:
                    background.add_task(alerts.handoff, business.name, str(decision.handoff_reason),
                                        decision.reasoning, transcript(session, business, conversation.id),
                                        conversation.customer_email, conversation.customer_phone,
                                        settings["cc_owner"], settings["ask_contact"])

            # Step 7: only customer-safe fields leave the server.
            contacts = biz_settings.pick(settings["contact_line"], conversation.language)
            view = convs.customer_view(bot_message, contacts)
            return {
                "conversation_id": str(conversation.id),
                "state": conversation.state,
                "message": {"id": bot_message.id, "role": "bot", "text": bot_message.text,
                            "action": bot_message.action},
                "panel": convs.panel_for(decision, brain.kb),
                "contacts": view.get("contacts"),
                # "Leave your email and we'll send you the answer", under a question for the owner.
                "ask_email": bool(settings["email_customers"] and decision.action is Action.ASK_OWNER
                                  and not conversation.customer_email),
                # "Leave your email or WhatsApp number so the team can contact you", under a complaint or lead.
                "ask_contact": bool(decision.handoff_reason in convs.TEAM_REASONS
                                    and convs.wants_contact(session, business, conversation, settings)),
            }

    @app.get("/api/b/{slug}/conversations/{conversation_id}/messages")
    def messages(slug: str, conversation_id: uuid.UUID, after: int = Query(0, ge=0)) -> dict:
        with session_factory() as session:
            business = business_or_404(session, slug)
            conversation = convs.get_conversation(session, business, conversation_id)
            if conversation is None:
                raise HTTPException(404, "Conversation not found.")
            settings = biz_settings.effective(business)
            contacts = biz_settings.pick(settings["contact_line"], conversation.language)
            rows = convs.messages_after(session, business, conversation, after)
            return {
                "state": conversation.state,
                "messages": [convs.customer_view(m, contacts) for m in rows],
                "email_capture": bool(settings["email_customers"]),
                "email_saved": conversation.customer_email is not None,
                "ask_contact": convs.wants_contact(session, business, conversation, settings),
            }

    @app.post("/api/b/{slug}/conversations/{conversation_id}/email")
    def save_email(slug: str, conversation_id: uuid.UUID, body: EmailRequest) -> dict:
        """The customer's email, for the owner's answer. Only on a business that emails its
        customers, and only on a conversation that has asked the owner something."""
        with session_factory() as session:
            business = business_or_404(session, slug)
            if not biz_settings.effective(business)["email_customers"]:
                raise HTTPException(404, "Not available.")
            conversation = convs.get_conversation(session, business, conversation_id)
            if conversation is None:
                raise HTTPException(404, "Conversation not found.")
            asked = session.scalar(select(Escalation.id).where(
                Escalation.business_id == business.id, Escalation.conversation_id == conversation.id,
                Escalation.kind == Action.ASK_OWNER).limit(1))
            if asked is None:
                raise HTTPException(409, "There's no question waiting for an answer in this chat.")
            conversation.customer_email = body.email
            session.commit()
        return {"ok": True}

    @app.post("/api/b/{slug}/conversations/{conversation_id}/contact")
    def save_contact(slug: str, conversation_id: uuid.UUID, body: ContactRequest,
                     background: BackgroundTasks) -> dict:
        """An email or WhatsApp number left after a complaint or lead, so the team can reach the
        customer (D-013). The first one is emailed to the team, as a reply to the complaint's email;
        a later change is only stored. It goes to the shop, never to the address typed."""
        with session_factory() as session:
            business = business_or_404(session, slug)
            settings = biz_settings.effective(business)
            if not settings["ask_contact"]:
                raise HTTPException(404, "Not available.")
            conversation = convs.get_conversation(session, business, conversation_id)
            if conversation is None:
                raise HTTPException(404, "Conversation not found.")
            handoff = convs.team_handoff(session, business, conversation)
            if handoff is None:
                raise HTTPException(409, "There's nothing for the team to contact you about in this chat.")
            parsed = parse_contact(body.contact)
            if parsed is None:
                raise HTTPException(422, "That isn't an email address or a phone number.")
            first = not (conversation.customer_email or conversation.customer_phone)
            kind, value = parsed
            if kind == "email":
                conversation.customer_email = value
            else:
                conversation.customer_phone = value
            session.commit()
            if first and settings["alerts"]:
                background.add_task(alerts.contact_left, business.name, handoff.reason, handoff.question,
                                    conversation.customer_email, conversation.customer_phone,
                                    transcript(session, business, conversation.id), settings["cc_owner"])
        return {"ok": True, "kind": kind}

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
    def owner_answer(escalation_id: int, body: OwnerText, background: BackgroundTasks,
                     access=Depends(owner_access)) -> dict:
        session, business = access
        result = owner_errors(lambda: owner.answer_ask_owner(session, business, escalation_id, body.text, client))
        if result.outcome.fallback_used:
            log.warning("learn call fell back for escalation %s: %s", escalation_id, result.outcome.problems)
        settings = biz_settings.effective(business)
        conversation = convs.get_conversation(session, business, result.escalation.conversation_id)
        # What the customer saw in the chat: the bot's relay, or the owner's own words if the learn
        # call failed. A deliberate "send nothing" (a null reply) emails nothing either.
        sent = (result.outcome.result.reply_to_customer if result.outcome.result else body.text)
        if settings["email_customers"] and conversation and conversation.customer_email and sent:
            question = owner.customer_question(session, business, result.escalation) or result.escalation.question
            background.add_task(alerts.answer_to_customer, biz_settings.display_name(business), conversation.customer_email,
                                conversation.language, question, sent,
                                biz_settings.pick(settings["contact_line"], conversation.language),
                                settings["reply_to"])
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

    # Direct edits from the Knowledge tab (D-015). Same safety as a saved answer: the KB must still
    # parse, a clash with another save is retried, and every change is kept (old and new text).
    def kb_errors(call):
        try:
            return owner_errors(call)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.put("/api/owner/{slug}/knowledge/{entry_id}")
    def owner_edit_entry(entry_id: str, body: EntryUpdate, access=Depends(owner_access)) -> dict:
        session, business = access
        saved = kb_errors(lambda: owner.edit_entry(session, business, entry_id, body.visibility, body.text,
                                                   body.base_text))
        if saved.changed:
            log.info("owner edited %s for %s (kb_version %s)", entry_id, business.slug, business.kb_version)
        return {"ok": True, "entry_id": saved.entry_id, "changed": saved.changed, "kb_version": business.kb_version}

    @app.post("/api/owner/{slug}/knowledge")
    def owner_add_entry(body: LearnEntry, access=Depends(owner_access)) -> dict:
        session, business = access
        saved = kb_errors(lambda: owner.add_entry(session, business, body.id, body.visibility, body.text))
        log.info("owner added %s for %s (kb_version %s)", saved.entry_id, business.slug, business.kb_version)
        return {"ok": True, "entry_id": saved.entry_id, "kb_version": business.kb_version}

    @app.get("/api/owner/{slug}/knowledge/export")
    def owner_export_kb(access=Depends(owner_access)) -> Response:
        session, business = access
        filename, markdown = owner.export_kb(business)
        return Response(markdown, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                 "Cache-Control": "no-store"})

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
        base = base_url(request)
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


def choose_client(max_tokens: int = 16000, warn: bool = True, timeout: float = MODEL_TIMEOUT_SECONDS) -> LLMClient:
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
    if model.startswith("gpt-"):
        # Our own SDK client, for a timeout: the SDK's default waits up to 10 minutes. It reads
        # OPENAI_API_KEY (and OPENAI_BASE_URL, for a gateway) from the environment.
        import openai

        from brain.llm import OpenAIClient

        sdk = openai.OpenAI(timeout=timeout, max_retries=1)
        return OpenAIClient(model, max_tokens=max_tokens, effort="medium", client=sdk)
    return make_client(model, effort="medium", max_tokens=max_tokens)


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


def deployment_from_env() -> Deployment:
    mode = os.environ.get("JAWAB_MODE", "multi").strip() or "multi"
    if mode not in ("multi", "single"):
        raise RuntimeError(f"JAWAB_MODE must be 'multi' or 'single', not {mode!r}")
    business = os.environ.get("JAWAB_BUSINESS", "").strip() or None
    if mode == "single":
        if not business:
            raise RuntimeError("JAWAB_MODE=single needs JAWAB_BUSINESS, the one business's slug")
        if not os.environ.get("DATABASE_URL"):
            # A real business's learned answers must survive restarts: never a throwaway SQLite file
            # by accident. (For a local try, set DATABASE_URL=sqlite:///plug.db on purpose.)
            raise RuntimeError("JAWAB_MODE=single needs DATABASE_URL")
    origins = [o.strip().rstrip("/") for o in os.environ.get("JAWAB_CORS_ORIGINS", "").split(",") if o.strip()]
    return Deployment(mode=mode, business=business if mode == "single" else None,
                      name=os.environ.get("JAWAB_DEPLOYMENT", "").strip() or "Jawab",
                      cors_origins=origins, cors_origin_regex=os.environ.get("JAWAB_CORS_ORIGIN_REGEX") or None)


def mailer_from_env() -> Mailer:
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        return NullMailer()
    # Until the sending domain is verified in Resend, its test sender only reaches the account's own address.
    return ResendMailer(key, os.environ.get("JAWAB_EMAIL_FROM", "").strip() or "Jawab <onboarding@resend.dev>")


def from_env() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    deployment = deployment_from_env()
    url = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    client = choose_client()
    draft_client = choose_client(max_tokens=DRAFT_MAX_TOKENS, warn=False, timeout=DRAFT_TIMEOUT_SECONDS)
    log.info("mode: %s%s; model client: %s; database: %s", deployment.mode,
             f" ({deployment.business})" if deployment.single else "", client.model, url.split("://")[0])
    limiter = RateLimiter(per_visitor=env_int("JAWAB_LIMIT_PER_HOUR", LIMIT_PER_VISITOR_PER_HOUR),
                          per_day=env_int("JAWAB_LIMIT_PER_DAY", LIMIT_PER_DAY))
    onboarding_limiter = RateLimiter(per_visitor=ONBOARDINGS_PER_VISITOR_PER_DAY,
                                     per_day=env_int("JAWAB_ONBOARDINGS_PER_DAY", ONBOARDINGS_PER_DAY), window=DAY)
    sandbox_limiter = RateLimiter(per_visitor=SANDBOXES_PER_VISITOR_PER_DAY, per_day=SANDBOXES_PER_DAY, window=DAY)
    alert_config = alerting.AlertConfig(deployment=deployment.name,
                                        owner=alerting.split_addresses(os.environ.get("OWNER_ALERT_EMAIL")),
                                        shop=alerting.split_addresses(os.environ.get("SHOP_ALERT_EMAILS")))
    return create_app(make_engine(url), client, limiter, draft_client, onboarding_limiter, sandbox_limiter,
                      deployment=deployment, mailer=mailer_from_env(), alert_config=alert_config)
