"""Self-serve onboarding at /start (spec section 8): interview, draft, publish.

The copied onboarding modules do the work: `Interview` asks the questions and keeps score,
`draft_kb` writes and checks the knowledge base. Here their state lives in `onboarding_sessions`
between requests instead of in files.

Model calls never run inside an open transaction: each step reads the session, closes the
transaction, calls the model, then saves only if the session hasn't moved on meanwhile (another
tab, a double click). A clash raises `Conflict`, and nothing is overwritten.
"""

import json
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db import Business, KBChange, OnboardingSession, new_owner_key
from app.services.owner import ENTRY_HEADING, SECTION, Conflict, NotFound
from brain.kb import KBError, parse_kb
from brain.llm import LLMClient
from onboarding.draft import DraftError, check_kb, draft_kb
from onboarding.interview import Interview, InterviewError
from onboarding.interview import interview_prompt as engine_interview_prompt
from onboarding.schema import Topic


QUICK, FULL = "quick", "full"
# The topics quick mode asks about (the engine's interview prompt, quick block); full mode asks about all.
QUICK_TOPICS = [Topic.BASICS, Topic.HOURS, Topic.SERVICES, Topic.PRICES, Topic.ESCALATION, Topic.STYLE]

SLUG_MAX = 40
SUGGESTION_COUNT = 4
SUGGESTION_MAX_CHARS = 80
PUBLISH_ATTEMPTS = 3  # a slug taken by someone publishing at the same moment: try the next one

log = logging.getLogger("jawab.onboarding")

class ModelFailed(Exception):
    """The model didn't produce a usable result (after its retry). The session is unchanged."""


class InvalidKB(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def topics_for(mode: str) -> list[str]:
    return [t.value for t in (QUICK_TOPICS if mode == QUICK else list(Topic))]


def interview_prompt(mode: str) -> str:
    """The interview prompt with the quick block kept only in quick mode (spec section 8)."""
    return engine_interview_prompt(quick=mode == QUICK)


def first_owner_message(business_name: str, pasted_text: str | None) -> str:
    """The owner always names the business, so the interviewer never has to ask for it."""
    text = f"Our business is called {business_name}."
    if pasted_text:
        text += f" Here is our info:\n\n{pasted_text}"
    return text


def _interview(client: LLMClient, row: OnboardingSession) -> Interview:
    return Interview(
        client=client,
        transcript=[dict(t) for t in row.transcript],
        covered={Topic(t) for t in row.covered},
        done=row.done,
        prompt=interview_prompt(row.mode),
    )


def _covered(interview: Interview) -> list[str]:
    return [t.value for t in Topic if t in interview.covered]


def _get(session: Session, session_id: uuid.UUID) -> OnboardingSession:
    row = session.get(OnboardingSession, session_id)
    if row is None:
        raise NotFound("No onboarding session with this ID.")
    return row


def _not_published(row: OnboardingSession) -> None:
    if row.business_id is not None:
        raise Conflict("This assistant is already published.")


def _ask(interview: Interview, owner_text: str) -> str:
    """One interviewer turn. Provider errors and two invalid turns both come back as ModelFailed."""
    try:
        return interview.reply(owner_text)
    except InterviewError as e:
        log.warning("interviewer failed: %s", e)
        raise ModelFailed("The interviewer got confused. Please try again.") from e
    except Exception as e:
        log.exception("interviewer call failed")
        raise ModelFailed("The interviewer is unavailable right now. Please try again in a minute.") from e


# --- The interview --------------------------------------------------------------------------------


def start(session_factory: sessionmaker[Session], client: LLMClient, business_name: str, mode: str,
          pasted_text: str | None) -> dict:
    """Create the session with the owner's first message and the interviewer's first question.
    Nothing is stored if the model fails."""
    interview = Interview(client=client, prompt=interview_prompt(mode))
    message = _ask(interview, first_owner_message(business_name, pasted_text))
    with session_factory() as session:
        row = OnboardingSession(id=uuid.uuid4(), business_name=business_name, mode=mode,
                                transcript=interview.transcript, covered=_covered(interview),
                                done=interview.done, open_questions=[], revision=1)
        session.add(row)
        session.commit()
        return {"session_id": str(row.id), "interviewer_message": message, "covered": row.covered,
                "done": row.done, "topics": topics_for(mode), "transcript": row.transcript}


def reply(session_factory: sessionmaker[Session], client: LLMClient, session_id: uuid.UUID, text: str) -> dict:
    with session_factory() as session:
        row = _get(session, session_id)
        _not_published(row)
        if row.done:
            raise Conflict("The interview is finished. Go on to the draft.")
        revision = row.revision
        interview = _interview(client, row)
    message = _ask(interview, text)  # outside any transaction
    with session_factory() as session:
        saved = session.execute(
            update(OnboardingSession)
            .where(OnboardingSession.id == session_id, OnboardingSession.revision == revision,
                   OnboardingSession.business_id.is_(None))
            .values(transcript=interview.transcript, covered=_covered(interview), done=interview.done,
                    revision=revision + 1)
        ).rowcount
        session.commit()
    if not saved:
        raise Conflict("This interview moved on in another tab or window. Reload the page to continue.")
    return {"interviewer_message": message, "covered": _covered(interview), "done": interview.done}


# --- Draft and checks -----------------------------------------------------------------------------


def sections(kb_markdown: str) -> list[dict]:
    """The KB as cards grouped by `## ` section, for the review step. Empty if it doesn't parse."""
    try:
        kb = parse_kb(kb_markdown)
    except KBError:
        return []
    groups: list[dict] = []
    current = None
    for line in kb_markdown.splitlines():
        if heading := SECTION.match(line):
            current = {"title": heading.group(1), "entries": []}
            groups.append(current)
        elif (entry := ENTRY_HEADING.match(line)) and entry.group(1) in kb.entries:
            if current is None:
                current = {"title": "General", "entries": []}
                groups.append(current)
            e = kb.entries[entry.group(1)]
            current["entries"].append({"id": e.id, "visibility": str(e.visibility), "status": e.status,
                                       "text": e.text})
    return [g for g in groups if g["entries"]]


def check(kb_markdown: str) -> dict:
    """What the review step shows for a KB: its problems (empty = publishable) and its cards."""
    return {"errors": check_kb(kb_markdown), "sections": sections(kb_markdown)}


def draft(session_factory: sessionmaker[Session], draft_client: LLMClient, session_id: uuid.UUID) -> dict:
    with session_factory() as session:
        row = _get(session, session_id)
        _not_published(row)
        interview = _interview(draft_client, row)
    try:
        result = draft_kb(interview, draft_client)  # outside any transaction
    except DraftError as e:
        log.warning("draft failed twice: %s", e)
        raise ModelFailed("The draft didn't come out right. Please try again.") from e
    except Exception as e:
        log.exception("draft call failed")
        raise ModelFailed("The writer is unavailable right now. Please try again in a minute.") from e
    with session_factory() as session:
        saved = session.execute(
            update(OnboardingSession)
            .where(OnboardingSession.id == session_id, OnboardingSession.business_id.is_(None))
            .values(draft_kb=result.kb_markdown, open_questions=list(result.open_questions))
        ).rowcount
        session.commit()
    if not saved:
        raise Conflict("This assistant is already published.")
    return {"kb_markdown": result.kb_markdown, "open_questions": list(result.open_questions),
            **check(result.kb_markdown)}


# --- Publishing -----------------------------------------------------------------------------------


@dataclass
class Published:
    slug: str
    owner_key: str


class StarterQuestions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    questions: list[str] = Field(description=f"Exactly {SUGGESTION_COUNT} short questions.")


SUGGESTIONS_PROMPT = f"""You write the starter questions shown as tappable chips on a small business's \
customer chat page.

Below is what customers may be told about the business. Write {SUGGESTION_COUNT} short questions a \
customer would really ask, each under 60 characters, about its main services and prices, and each \
answerable from this information. Write them in the business's default language, given below. \
No numbering, no quotes."""


def starter_questions(client: LLMClient, kb_markdown: str) -> list[str]:
    """Four starter questions from the KB's public entries. [] on any failure: chips are optional."""
    try:
        kb = parse_kb(kb_markdown)
        public = "\n\n".join(f"[{e.id}]\n{e.text}" for i, e in kb.entries.items() if kb.is_public(i))
        language = kb.metadata.get("default_language") or "en"
        messages = [{"role": "user", "content": f"Default language: {language}\n\n<public_information>\n"
                                                f"{public}\n</public_information>"}]
        completion = client.complete(SUGGESTIONS_PROMPT, messages, StarterQuestions.model_json_schema())
        questions = StarterQuestions.model_validate_json(completion.text).questions
    except (ValidationError, KBError, json.JSONDecodeError) as e:
        log.warning("starter questions skipped: %s", e)
        return []
    except Exception:
        log.exception("starter questions call failed")
        return []
    questions = [q for q in questions if q and len(q) <= SUGGESTION_MAX_CHARS]
    return questions[:SUGGESTION_COUNT]


def slugify(name: str) -> str:
    """'Noor Tailoring & Alterations' -> 'noor-tailoring-alterations'. Non-Latin names -> 'business'."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug[:SLUG_MAX].strip("-") or "business"


def _free_slug(session: Session, base: str) -> str:
    taken = set(session.scalars(select(Business.slug).where(Business.slug.like(f"{base}%"))))
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _published(session: Session, row: OnboardingSession) -> Published:
    business = session.get(Business, row.business_id)
    return Published(business.slug, business.owner_key)


DEFAULT_LANGUAGES = "en, ar"  # Jawab serves its customers in English and Arabic (and Arabizi)


def with_default_languages(kb_markdown: str) -> str:
    """Add `languages: en, ar` to the front matter if the KB doesn't list its languages, so the
    engine's Arabic notes (dialects, Arabizi) are on for every business set up through /start."""
    lines = kb_markdown.split("\n")
    if not lines or lines[0].strip() != "---":
        return kb_markdown
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None or any(line.startswith("languages:") for line in lines[1:end]):
        return kb_markdown
    return "\n".join(lines[:end] + [f"languages: {DEFAULT_LANGUAGES}"] + lines[end:])


def publish(session_factory: sessionmaker[Session], client: LLMClient, session_id: uuid.UUID,
            kb_markdown: str) -> Published:
    """Create the business from a reviewed KB. Publishing again returns the same business."""
    with session_factory() as session:
        row = _get(session, session_id)
        if row.business_id is not None:
            return _published(session, row)
        business_name = row.business_name
    problems = check_kb(kb_markdown)
    if problems:
        raise InvalidKB(problems)
    kb_markdown = with_default_languages(kb_markdown)
    kb = parse_kb(kb_markdown)
    name = kb.metadata.get("business") or business_name
    # The slug follows the name the owner typed ("Noor Tailoring" -> noor-tailoring), which is often
    # shorter than the KB's full name; the KB's name helps when the typed one is in Arabic script.
    slug_base = slugify(business_name)
    if slug_base == "business":
        slug_base = slugify(name)
    suggestions = starter_questions(client, kb_markdown)  # outside any transaction

    for _ in range(PUBLISH_ATTEMPTS):
        with session_factory() as session:
            row = _get(session, session_id)
            if row.business_id is not None:  # published meanwhile (a double click)
                return _published(session, row)
            business = Business(slug=_free_slug(session, slug_base), name=name, owner_key=new_owner_key(),
                                kb_markdown=kb_markdown, kb_version=1, suggestions=suggestions)
            session.add(business)
            try:
                session.flush()
            except IntegrityError:  # the slug was taken at the same moment
                session.rollback()
                continue
            session.add(KBChange(business_id=business.id, change="initial", new_text=kb_markdown))
            claimed = session.execute(
                update(OnboardingSession)
                .where(OnboardingSession.id == session_id, OnboardingSession.business_id.is_(None))
                .values(business_id=business.id, draft_kb=kb_markdown)
            ).rowcount
            if not claimed:
                session.rollback()
                continue  # the next round returns the business the other request created
            session.commit()
            log.info("published business %s", business.slug)
            return Published(business.slug, business.owner_key)
    raise Conflict("Couldn't publish right now. Please try again.")


# --- Resuming ------------------------------------------------------------------------------------


def state(session_factory: sessionmaker[Session], session_id: uuid.UUID) -> tuple[dict, Published | None]:
    """Everything the page needs to pick up where the owner left off."""
    with session_factory() as session:
        row = _get(session, session_id)
        view = {
            "session_id": str(row.id),
            "business_name": row.business_name,
            "mode": row.mode,
            "transcript": row.transcript,
            "covered": row.covered,
            "topics": topics_for(row.mode),
            "done": row.done,
            "draft": None,
        }
        if row.draft_kb is not None:
            view["draft"] = {"kb_markdown": row.draft_kb, "open_questions": row.open_questions,
                             **check(row.draft_kb)}
        published = _published(session, row) if row.business_id is not None else None
        return view, published
