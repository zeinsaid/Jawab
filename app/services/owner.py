"""The owner's side (spec section 7): the inbox, relaying answers, learning, handoffs, stats, the KB view,
and resetting the demo business.

Every query filters by `business_id`. The relay + learn model call runs outside any open
transaction, and the escalation is only claimed afterwards with a conditional update, so two
answers to the same question can't both be sent.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.db import SEED_BUSINESSES, Business, Conversation, Escalation, KBChange, Message, utcnow
from app.services import conversations as convs
from app.services import kb_edit
from brain.learn import Learner, LearnOutcome
from brain.kb import KBError, parse_kb
from brain.llm import LLMClient
from brain.schema import Action, Role

TRANSCRIPT_MESSAGES = 10  # messages shown with each escalation and sent to the learn call
RECENT_ESCALATIONS = 15  # answered/closed escalations listed under the pending ones

PENDING, ANSWERED, CLOSED = "pending", "answered", "closed"
SAVED, EDITED, ONCE = "saved", "edited", "once"
KB_SAVE_ATTEMPTS = 2  # a save that clashes with another one at the same moment is retried once


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


# --- Reading --------------------------------------------------------------------------------------


def get_escalation(session: Session, business: Business, escalation_id: int) -> Escalation:
    escalation = session.scalar(
        select(Escalation).where(Escalation.id == escalation_id, Escalation.business_id == business.id)
    )
    if escalation is None:
        raise NotFound("Escalation not found.")
    return escalation


def recent_messages(session: Session, business: Business, conversation_id: uuid.UUID,
                    limit: int = TRANSCRIPT_MESSAGES) -> list[Message]:
    """The last `limit` messages of a conversation, oldest first."""
    rows = session.scalars(
        select(Message)
        .where(Message.business_id == business.id, Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))


def list_escalations(session: Session, business: Business) -> list[dict]:
    """Pending escalations (newest first), then the most recently answered or closed ones."""
    pending = session.scalars(
        select(Escalation)
        .where(Escalation.business_id == business.id, Escalation.status == PENDING)
        .order_by(Escalation.created_at.desc(), Escalation.id.desc())
    ).all()
    recent = session.scalars(
        select(Escalation)
        .where(Escalation.business_id == business.id, Escalation.status != PENDING)
        .order_by(Escalation.answered_at.desc(), Escalation.id.desc())
        .limit(RECENT_ESCALATIONS)
    ).all()
    kb = parse_kb(business.kb_markdown)
    return [escalation_view(session, business, e, kb) for e in [*pending, *recent]]


def escalation_view(session: Session, business: Business, escalation: Escalation, kb=None) -> dict:
    """What the owner page shows for one escalation. The model's reasoning and cited entries of bot
    messages stay out: the transcript is what the customer saw, plus each bot message's action."""
    conversation = session.scalar(
        select(Conversation).where(Conversation.id == escalation.conversation_id,
                                   Conversation.business_id == business.id)
    )
    messages = recent_messages(session, business, escalation.conversation_id)
    view = {
        "id": escalation.id,
        "kind": escalation.kind,
        "reason": escalation.reason,  # handoffs: abuse, complaint, lead, other
        "status": escalation.status,
        "question": escalation.question,
        "conversation_id": str(escalation.conversation_id),
        "conversation_state": conversation.state if conversation else None,
        "customer_language": conversation.language if conversation else None,
        # Owner-only: where the answer will be emailed, if the customer left an address.
        "customer_email": conversation.customer_email if conversation else None,
        "customer_phone": conversation.customer_phone if conversation else None,  # left after a complaint or lead
        "created_at": _iso(escalation.created_at),
        "answered_at": _iso(escalation.answered_at),
        "owner_answer": escalation.owner_answer,
        "messages": [
            {"id": m.id, "role": m.role, "text": m.text, "action": m.action, "created_at": _iso(m.created_at)}
            for m in messages
        ],
        "relay": None,
        "learn_decision": escalation.learn_decision,
        "learned_entry_id": None,
    }
    if escalation.learn_decision in (SAVED, EDITED):
        view["learned_entry_id"] = session.scalar(
            select(KBChange.entry_id)
            .where(KBChange.business_id == business.id, KBChange.source_escalation_id == escalation.id)
            .order_by(KBChange.id.desc())
            .limit(1)
        )
    if escalation.kind == Action.ASK_OWNER and escalation.status == ANSWERED:
        proposal = escalation.learn_proposal
        if proposal is None:  # the learn call failed twice: the owner's answer went as a Team message
            view["relay"] = {"fallback": True, "sent_as": "staff", "sent_text": escalation.owner_answer,
                             "proposal": None, "old_text": None}
        else:
            reply = proposal.get("reply_to_customer")
            kb = kb or parse_kb(business.kb_markdown)
            target = proposal.get("target_entry_id")
            old = kb.entries.get(target) if proposal.get("learn_action") == "update" and target else None
            view["relay"] = {"fallback": False, "sent_as": "bot" if reply else None, "sent_text": reply,
                             "proposal": proposal, "old_text": old.text if old else None}
    return view


def stats(session: Session, business: Business) -> dict:
    """The stats strip. "This week" is the last 7 days.

    The bot's share counts the bot's own replies to customer messages: `answer` actions over all
    of them. A bot message relaying the owner's answer is the owner's work, so it counts on neither
    side; it's the only kind of `answer` with no cited entries (a real answer must cite one).
    """
    since = utcnow() - timedelta(days=7)
    customer_messages = session.scalar(
        select(func.count()).select_from(Message).where(
            Message.business_id == business.id, Message.role == Role.CUSTOMER, Message.created_at >= since)
    )
    bot_rows = session.execute(
        select(Message.action, Message.cited_entries).where(
            Message.business_id == business.id, Message.role == Role.BOT, Message.created_at >= since)
    ).all()
    replies = [(action, cited) for action, cited in bot_rows if not (action == Action.ANSWER and not cited)]
    answered = sum(1 for action, _ in replies if action == Action.ANSWER)
    learned = session.scalar(
        select(func.count()).select_from(KBChange).where(
            KBChange.business_id == business.id, KBChange.source_escalation_id.is_not(None))
    )
    pending = session.scalar(
        select(func.count()).select_from(Escalation).where(
            Escalation.business_id == business.id, Escalation.status == PENDING)
    )
    return {
        "messages_this_week": customer_messages,
        "answered_by_bot_pct": round(100 * answered / len(replies)) if replies else None,
        "questions_learned": learned,
        "pending": pending,
    }


SECTION = re.compile(r"^## (.+?)\s*$")
ENTRY_HEADING = re.compile(r"^### (\S+)\s*$")


def knowledge(session: Session, business: Business) -> dict:
    """The KB as the owner sees it: learned entries first (newest first, with when and from which
    customer question), then the other entries grouped by the `## ` section they sit under."""
    kb = parse_kb(business.kb_markdown)
    origins = learned_origins(session, business)
    edited = last_manual_changes(session, business)
    learned_ids = [i for i, e in kb.entries.items() if e.status == "learned"]
    learned_ids.sort(key=lambda i: origins.get(i, {}).get("learned_at") or edited.get(i) or "", reverse=True)

    def view(entry_id: str) -> dict:
        e = kb.entries[entry_id]
        item = {"id": e.id, "visibility": str(e.visibility), "status": e.status, "text": e.text,
                "edited_at": edited.get(e.id)}
        if e.status == "learned":
            origin = origins.get(e.id, {})
            item["learned_at"] = origin.get("learned_at") or edited.get(e.id)
            item["source_question"] = origin.get("source_question")
        return item

    sections: list[dict] = []
    current = None
    for line in business.kb_markdown.splitlines():
        if heading := SECTION.match(line):
            current = {"title": heading.group(1), "entries": []}
            sections.append(current)
        elif (entry := ENTRY_HEADING.match(line)) and entry.group(1) in kb.entries:
            if entry.group(1) in learned_ids:
                continue  # listed once, in the learned group
            if current is None:
                current = {"title": "General", "entries": []}
                sections.append(current)
            current["entries"].append(view(entry.group(1)))
    return {
        "name": business.name,
        "kb_version": business.kb_version,
        "entry_count": len(kb.entries),
        "learned": [view(i) for i in learned_ids],
        "sections": [s for s in sections if s["entries"]],
        "can_reset_demo": demo_seed(business) is not None,
    }


def learned_origins(session: Session, business: Business) -> dict[str, dict]:
    """For each entry learned from an escalation: when (its latest change) and the customer's
    message that led to the question (the last one before the bot asked the owner)."""
    changes = session.execute(
        select(KBChange.entry_id, KBChange.created_at, Escalation.conversation_id, Escalation.message_id)
        .join(Escalation, Escalation.id == KBChange.source_escalation_id)
        .where(KBChange.business_id == business.id, Escalation.business_id == business.id)
        .order_by(KBChange.id)
    ).all()
    origins: dict[str, dict] = {}
    for entry_id, created_at, conversation_id, message_id in changes:  # later changes win
        question = session.scalar(
            select(Message.text)
            .where(Message.business_id == business.id, Message.conversation_id == conversation_id,
                   Message.role == Role.CUSTOMER, Message.id < message_id)
            .order_by(Message.id.desc())
            .limit(1)
        )
        origins[entry_id] = {"learned_at": _iso(created_at), "source_question": question}
    return origins


def customer_question(session: Session, business: Business, escalation: Escalation) -> str | None:
    """The customer's own words that led to an escalation: their last message before the bot's."""
    return session.scalar(
        select(Message.text)
        .where(Message.business_id == business.id, Message.conversation_id == escalation.conversation_id,
               Message.role == Role.CUSTOMER, Message.id < escalation.message_id)
        .order_by(Message.id.desc())
        .limit(1)
    )


# --- Acting ---------------------------------------------------------------------------------------


@dataclass
class AnswerResult:
    escalation: Escalation
    outcome: LearnOutcome


def answer_ask_owner(session: Session, business: Business, escalation_id: int, owner_answer: str,
                     client: LLMClient) -> AnswerResult:
    """Relay the owner's answer to the customer and store the learning proposal (not applied)."""
    escalation = get_escalation(session, business, escalation_id)
    if escalation.kind != Action.ASK_OWNER:
        raise Conflict("This isn't a question for the owner.")
    if escalation.status != PENDING:
        raise Conflict("This question has already been answered.")

    history = convs.turns_from(recent_messages(session, business, escalation.conversation_id))
    question = escalation.question
    learner = Learner(parse_kb(business.kb_markdown), client)
    session.commit()  # no transaction stays open while the model works

    outcome = learner.run(history, question, owner_answer)

    # Claim the escalation now; if someone else answered meanwhile, send nothing.
    claimed = session.execute(
        update(Escalation)
        .where(Escalation.id == escalation_id, Escalation.business_id == business.id, Escalation.status == PENDING)
        .values(status=ANSWERED, owner_answer=owner_answer, answered_at=utcnow(),
                learn_proposal=outcome.result.model_dump(mode="json") if outcome.result else None)
        .execution_options(synchronize_session=False)
    ).rowcount
    if not claimed:
        session.rollback()
        raise Conflict("This question has already been answered.")

    conversation = convs.get_conversation(session, business, escalation.conversation_id)
    if outcome.result is None:
        convs.add_message(session, business, conversation, Role.STAFF, owner_answer)
    elif outcome.result.reply_to_customer:
        convs.add_message(session, business, conversation, Role.BOT, outcome.result.reply_to_customer,
                          action=str(Action.ANSWER), cited_entries=[],
                          reasoning=f"Relayed the owner's answer. {outcome.result.reasoning}")
    # Back to the bot, unless a person has taken the chat over in the meantime.
    if conversation.state not in convs.QUIET:
        conversation.state = convs.BOT_ACTIVE
    session.commit()
    session.refresh(escalation)
    return AnswerResult(escalation, outcome)


def _pending_handoff(session: Session, business: Business, escalation_id: int) -> Escalation:
    escalation = get_escalation(session, business, escalation_id)
    if escalation.kind != Action.HANDOFF:
        raise Conflict("This isn't a handed-off chat.")
    if escalation.status != PENDING:
        raise Conflict("This chat has already been given back to the bot.")
    return escalation


def reply_to_handoff(session: Session, business: Business, escalation_id: int, text: str) -> Escalation:
    """A message from the team, sent to the customer as-is. No model call."""
    escalation = _pending_handoff(session, business, escalation_id)
    conversation = convs.get_conversation(session, business, escalation.conversation_id)
    convs.add_message(session, business, conversation, Role.STAFF, text)
    session.commit()
    return escalation


def give_back_to_bot(session: Session, business: Business, escalation_id: int) -> Escalation:
    escalation = _pending_handoff(session, business, escalation_id)
    conversation = convs.get_conversation(session, business, escalation.conversation_id)
    conversation.state = convs.BOT_ACTIVE
    conversation.updated_at = utcnow()
    escalation.status = CLOSED
    escalation.answered_at = utcnow()
    session.commit()
    return escalation


@dataclass
class LearnApplied:
    ok: bool
    error: str | None = None
    entry_id: str | None = None


def apply_learning(session: Session, business: Business, escalation_id: int, decision: str,
                   edited_entry: dict | None = None) -> LearnApplied:
    """The owner's decision on a learning card (spec section 7, "Applying a saved entry").

    "saved" applies the stored proposal, "edited" applies `edited_entry` ({id, visibility, text})
    instead, "once" changes nothing in the KB. A KB that wouldn't parse is never saved: the result
    is ok=False with the reason. Deciding twice raises Conflict.
    """
    escalation = get_escalation(session, business, escalation_id)
    if escalation.kind != Action.ASK_OWNER or escalation.status != ANSWERED:
        raise Conflict("Only an answered question can be saved to the knowledge base.")
    if escalation.learn_decision is not None:
        raise Conflict("This answer has already been saved or skipped.")

    if decision == ONCE:
        _claim_decision(session, business, escalation_id, ONCE)
        session.commit()
        return LearnApplied(ok=True)

    proposal = escalation.learn_proposal or {}
    action = proposal.get("learn_action")
    target = proposal.get("target_entry_id") if action == "update" else None
    if decision == SAVED:
        entry = proposal.get("proposed_entry")
        if action not in ("add", "update") or not entry:
            return LearnApplied(ok=False, error="There's no proposed entry to save. Use Edit to write one.")
    elif decision == EDITED:
        entry = edited_entry
        if not entry:
            return LearnApplied(ok=False, error="Write the entry to save.")
    else:
        raise ValueError(f"unknown decision: {decision}")

    entry_id = str(entry.get("id", "")).strip()
    visibility = str(entry.get("visibility", "")).strip()
    text = str(entry.get("text", "")).strip()
    if problems := kb_edit.entry_problems(entry_id, visibility, text):
        return LearnApplied(ok=False, error=" ".join(problems))
    # An edit updates the proposed entry only if it keeps that entry's ID; otherwise it's a new one.
    is_update = target is not None and entry_id == target

    for _ in range(KB_SAVE_ATTEMPTS):
        session.refresh(business)
        version, markdown = business.kb_version, business.kb_markdown
        kb = parse_kb(markdown)
        old_text = None
        if is_update:
            if target not in kb.entries:
                return LearnApplied(ok=False, error=f"The entry {target} no longer exists. Use Edit to add it as a new one.")
            new_markdown, old_text = kb_edit.update_entry(markdown, target, visibility, text)
            saved_id, change = target, "update"
        else:
            saved_id, change = kb_edit.free_id(entry_id, kb.entries), "add"
            new_markdown = kb_edit.add_entry(markdown, saved_id, visibility, text)
        try:
            parse_kb(new_markdown)
        except KBError as e:
            session.rollback()
            return LearnApplied(ok=False, error=f"Nothing was saved: the knowledge base wouldn't be valid ({e}).")

        # Only if nobody saved another change meanwhile; otherwise start again from the new KB.
        bumped = session.execute(
            update(Business)
            .where(Business.id == business.id, Business.kb_version == version)
            .values(kb_markdown=new_markdown, kb_version=version + 1)
            .execution_options(synchronize_session=False)
        ).rowcount
        if not bumped:
            session.rollback()
            continue
        _claim_decision(session, business, escalation_id, decision)
        session.add(KBChange(business_id=business.id, entry_id=saved_id, change=change, old_text=old_text,
                             new_text=text, source_escalation_id=escalation_id))
        session.commit()
        session.refresh(business)
        return LearnApplied(ok=True, entry_id=saved_id)

    raise Conflict("The knowledge base was changed at the same moment. Please try again.")


def _claim_decision(session: Session, business: Business, escalation_id: int, decision: str) -> None:
    """Record the decision only if there isn't one yet; otherwise undo everything and refuse."""
    claimed = session.execute(
        update(Escalation)
        .where(Escalation.id == escalation_id, Escalation.business_id == business.id,
               Escalation.learn_decision.is_(None))
        .values(learn_decision=decision)
        .execution_options(synchronize_session=False)
    ).rowcount
    if not claimed:
        session.rollback()
        raise Conflict("This answer has already been saved or skipped.")


def demo_seed(business: Business) -> dict | None:
    """The seed of a demo business (The Plug on the public demo, or a visitor's sandbox copy of
    it), or None. The database's `demo` flag decides, so where The Plug runs for real
    (single-business mode) it can never be reset."""
    if not business.demo:
        return None
    slug = business.sandbox_of or business.slug
    return next((s for s in SEED_BUSINESSES if s["slug"] == slug and s.get("demo")), None)


def reset_demo(session: Session, business: Business) -> int:
    """Put a demo business back to its starting point: the KB from its file (with a new version, so
    the cached brain is rebuilt) and no conversations, messages or escalations. The KB changes
    learned from those escalations go too, so "questions learned" starts again at 0.
    Returns the new kb_version."""
    seed = demo_seed(business)
    if seed is None:
        raise NotFound("Only the demo business can be reset.")
    kb_markdown = Path(seed["kb_path"]).read_text(encoding="utf-8")
    parse_kb(kb_markdown)  # never save a KB that wouldn't parse

    session.execute(delete(KBChange).where(
        KBChange.business_id == business.id,
        KBChange.source_escalation_id.is_not(None) | KBChange.change.in_(MANUAL_CHANGES)))
    session.execute(delete(Escalation).where(Escalation.business_id == business.id))
    session.execute(delete(Message).where(Message.business_id == business.id))
    session.execute(delete(Conversation).where(Conversation.business_id == business.id))
    session.execute(
        update(Business).where(Business.id == business.id)
        .values(kb_markdown=kb_markdown, kb_version=Business.kb_version + 1)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    session.refresh(business)
    return business.kb_version


# --- Direct edits from the Knowledge tab (D-015) ------------------------------------------------------

MANUAL_EDIT, MANUAL_ADD = "manual_edit", "manual_add"
MANUAL_CHANGES = (MANUAL_EDIT, MANUAL_ADD)


@dataclass
class EntrySaved:
    entry_id: str
    changed: bool  # False when the owner saved it unchanged


def _save_kb(session: Session, business: Business, build) -> EntrySaved:
    """Shared by the direct edits: `build(markdown, kb)` returns (new_markdown, KBChange fields, EntrySaved)
    or raises NotFound / Conflict / ValueError (a problem to show the owner). A KB that wouldn't parse is
    never saved, and a save that clashes with another one at the same moment starts again from the new KB."""
    for _ in range(KB_SAVE_ATTEMPTS):
        session.refresh(business)
        version, markdown = business.kb_version, business.kb_markdown
        new_markdown, change, result = build(markdown, parse_kb(markdown))
        if new_markdown is None:  # nothing to change
            return result
        try:
            parse_kb(new_markdown)
        except KBError as e:
            session.rollback()
            raise ValueError(f"Nothing was saved: the knowledge base wouldn't be valid ({e}).") from e
        bumped = session.execute(
            update(Business)
            .where(Business.id == business.id, Business.kb_version == version)
            .values(kb_markdown=new_markdown, kb_version=version + 1)
            .execution_options(synchronize_session=False)
        ).rowcount
        if not bumped:
            session.rollback()
            continue
        session.add(KBChange(business_id=business.id, **change))
        session.commit()
        session.refresh(business)
        return result
    raise Conflict("The knowledge base was changed at the same moment. Please try again.")


def edit_entry(session: Session, business: Business, entry_id: str, visibility: str, text: str,
               base_text: str | None = None) -> EntrySaved:
    """The owner rewrites an existing entry in place (same ID, same position). A placeholder becomes
    confirmed (the owner has now checked it); other entries keep their status. `base_text` is the text
    the owner started from: if the entry has changed since (say, a saved answer updated it), refuse
    rather than overwrite that change."""
    text = text.strip()
    if problems := kb_edit.entry_problems(entry_id, visibility, text):
        raise ValueError(" ".join(problems))

    def build(markdown, kb):
        current = kb.entries.get(entry_id)
        if current is None:
            raise NotFound(f"There's no entry {entry_id} any more. Reload the knowledge base.")
        if base_text is not None and current.text.strip() != base_text.strip():
            raise Conflict("This entry was changed after you opened it. Reload the knowledge base and edit it again.")
        status = "confirmed" if current.status == "placeholder" else current.status
        if current.text.strip() == text and str(current.visibility) == visibility and status == current.status:
            return None, None, EntrySaved(entry_id, changed=False)
        new_markdown, old_text = kb_edit.update_entry(markdown, entry_id, visibility, text, status)
        return new_markdown, {"entry_id": entry_id, "change": MANUAL_EDIT, "old_text": old_text,
                              "new_text": text}, EntrySaved(entry_id, changed=True)

    return _save_kb(session, business, build)


def add_entry(session: Session, business: Business, entry_id: str, visibility: str, text: str) -> EntrySaved:
    """The owner writes a new entry. It goes into the "Learned from the owner" section, like a saved
    answer. A taken ID is refused (the owner picks another) rather than renamed behind their back."""
    text = text.strip()
    if problems := kb_edit.entry_problems(entry_id, visibility, text):
        raise ValueError(" ".join(problems))

    def build(markdown, kb):
        if entry_id in kb.entries:
            raise Conflict(f"There's already an entry called {entry_id}. Pick another ID, or edit that one.")
        new_markdown = kb_edit.add_entry(markdown, entry_id, visibility, text)
        return new_markdown, {"entry_id": entry_id, "change": MANUAL_ADD, "old_text": None,
                              "new_text": text}, EntrySaved(entry_id, changed=True)

    return _save_kb(session, business, build)


def last_manual_changes(session: Session, business: Business) -> dict[str, str]:
    """When each entry was last edited or added from the Knowledge tab (ISO time), for its label."""
    rows = session.execute(
        select(KBChange.entry_id, KBChange.created_at)
        .where(KBChange.business_id == business.id, KBChange.change.in_(MANUAL_CHANGES))
        .order_by(KBChange.id)
    ).all()
    return {entry_id: _iso(created_at) for entry_id, created_at in rows if entry_id}  # later rows win


def export_kb(business: Business) -> tuple[str, str]:
    """The live knowledge base as a markdown file: (filename, content)."""
    return f"{business.slug}-kb-v{business.kb_version}.md", business.kb_markdown


def _iso(value) -> str | None:
    return value.isoformat() if value else None
