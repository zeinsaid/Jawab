"""Conversations and messages: the customer chat flow from spec section 6.

The history the brain sees always comes from the database, so a customer can't fake staff or bot
turns. Internal entries and the model's reasoning are stored here but never returned to customers.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Business, Conversation, Escalation, Message, utcnow
from brain.kb import KnowledgeBase
from brain.schema import Action, BrainDecision, HandoffReason, IncomingMessage, Role, Turn

HISTORY_MESSAGES = 40  # earlier messages loaded for the brain (it reads the last 10 itself, D-023)
SUMMARY_CHARS = 160  # length of a handoff's one-line summary

BOT_ACTIVE = "bot_active"
WAITING_ON_OWNER = "waiting_on_owner"
HUMAN_HANDOFF = "human_handoff"
CLOSED = "closed"
ENDED = "ended"  # an abuse goodbye: the bot stays silent and nobody is waiting to reply
QUIET = (HUMAN_HANDOFF, ENDED)  # states where a new customer message gets no bot reply
NOTIFIED = "notified"  # an escalation's status: the team was told outside Jawab, nothing to do in the inbox
TEAM_REASONS = (HandoffReason.COMPLAINT, HandoffReason.LEAD)  # handoffs the shop is emailed about

GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")
LANGS = ("en", "el", "ar")


def detect_language(text: str, page_language: str | None) -> str:
    """The customer's language, for the texts Jawab adds itself (offline message, contact line,
    the answer email). The script decides when it can; Latin text (English, Greeklish, Arabizi)
    takes the page's language, which the customer chose."""
    if ARABIC.search(text):
        return "ar"
    if GREEK.search(text):
        return "el"
    return page_language if page_language in LANGS else "en"


def needs_contacts(action: str | None, reason: str | None) -> bool:
    """Replies that need a person end with the shop's contacts; an abuse goodbye gets nothing."""
    return action == Action.ASK_OWNER or (action == Action.HANDOFF and reason != HandoffReason.ABUSE)


def get_conversation(session: Session, business: Business, conversation_id: uuid.UUID) -> Conversation | None:
    return session.scalar(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.business_id == business.id)
    )


def find_or_create_conversation(session: Session, business: Business,
                                conversation_id: uuid.UUID | None) -> Conversation:
    """The customer's conversation, or a new one if the ID is missing or unknown for this business."""
    conversation = get_conversation(session, business, conversation_id) if conversation_id else None
    if conversation is None:
        conversation = Conversation(business_id=business.id, state=BOT_ACTIVE)
        session.add(conversation)
        session.flush()
    elif conversation.state == CLOSED:
        conversation.state = BOT_ACTIVE  # a closed chat that gets a new message starts again
    return conversation


def add_message(session: Session, business: Business, conversation: Conversation, role: str, text: str,
                **fields) -> Message:
    message = Message(business_id=business.id, conversation_id=conversation.id, role=role, text=text, **fields)
    session.add(message)
    conversation.updated_at = utcnow()
    session.flush()
    return message


def history_before(session: Session, business: Business, conversation: Conversation,
                   message: Message) -> list[Turn]:
    """Up to HISTORY_MESSAGES messages before `message`, oldest first, as brain turns."""
    rows = session.scalars(
        select(Message)
        .where(Message.business_id == business.id, Message.conversation_id == conversation.id,
               Message.id < message.id)
        .order_by(Message.id.desc())
        .limit(HISTORY_MESSAGES)
    ).all()
    return turns_from(list(reversed(rows)))


def turns_from(rows: list[Message]) -> list[Turn]:
    """Messages (oldest first) as brain turns, exactly as the customer saw them."""
    turns = []
    for row in rows:
        if not row.text.strip():
            continue
        if row.role == Role.BOT:
            turns.append(Turn(role=Role.BOT, text=row.text, action=Action(row.action or Action.ANSWER)))
        elif row.role == Role.STAFF:
            turns.append(Turn(role=Role.STAFF, text=row.text))
        else:
            turns.append(Turn(role=Role.CUSTOMER, text=row.text))
    return turns


def build_incoming(session: Session, business: Business, conversation: Conversation,
                   message: Message) -> IncomingMessage:
    return IncomingMessage(text=message.text, history=history_before(session, business, conversation, message))


def one_line(text: str, limit: int = SUMMARY_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def record_decision(session: Session, business: Business, conversation: Conversation,
                    customer_message: Message, decision: BrainDecision,
                    handoffs: str = "inbox") -> tuple[Message, Escalation | None]:
    """Save the bot's reply, then update the conversation state and the owner's inbox (steps 5-6).

    Returns the bot message and the escalation this created, if any (an ask_owner that only
    restates a pending question creates none, and neither does a repeat handoff in "notify" mode),
    so the caller can send one alert per new event. `handoffs` is the business's setting (D-013)."""
    reason = str(decision.handoff_reason) if decision.handoff_reason else None
    bot_message = add_message(
        session, business, conversation, Role.BOT, decision.reply or "",
        action=str(decision.action), cited_entries=list(decision.cited_entries), reasoning=decision.reasoning,
        handoff_reason=reason,
    )
    created = None

    if decision.action is Action.ANSWER:
        # A new answerable question while waiting on the owner keeps the chat waiting.
        if conversation.state != WAITING_ON_OWNER:
            conversation.state = BOT_ACTIVE
    elif decision.action is Action.ASK_OWNER:
        conversation.state = WAITING_ON_OWNER
        pending = session.scalar(
            select(Escalation).where(
                Escalation.business_id == business.id, Escalation.conversation_id == conversation.id,
                Escalation.kind == Action.ASK_OWNER, Escalation.status == "pending",
            )
        )
        if pending:
            pending.question = decision.question_for_owner  # the prompt restates the whole request
        else:
            created = Escalation(
                business_id=business.id, conversation_id=conversation.id, message_id=bot_message.id,
                kind=str(Action.ASK_OWNER), question=decision.question_for_owner, status="pending",
            )
    elif decision.action is Action.HANDOFF and decision.handoff_reason is HandoffReason.ABUSE:
        # Kept for the record but closed at once: nobody needs to act on it, and the troll's next
        # messages cost no model call.
        conversation.state = ENDED
        created = Escalation(
            business_id=business.id, conversation_id=conversation.id, message_id=bot_message.id,
            kind=str(Action.HANDOFF), reason=reason, question=one_line(customer_message.text),
            status=CLOSED, answered_at=utcnow(),
        )
    elif decision.action is Action.HANDOFF and handoffs == "notify":
        # The team handles it outside Jawab (the shop's email, the phone): the inbox only records
        # it, and the bot keeps answering. One record per reason per chat, so a customer who keeps
        # complaining doesn't email the shop again with every message.
        repeat = session.scalar(
            select(Escalation.id).where(
                Escalation.business_id == business.id, Escalation.conversation_id == conversation.id,
                Escalation.kind == Action.HANDOFF, Escalation.reason == reason,
            ).limit(1)
        )
        if repeat is None:
            created = Escalation(
                business_id=business.id, conversation_id=conversation.id, message_id=bot_message.id,
                kind=str(Action.HANDOFF), reason=reason, question=one_line(customer_message.text),
                status=NOTIFIED, answered_at=utcnow(),
            )
    elif decision.action is Action.HANDOFF:
        # A person replies in the inbox; the bot stays out of it until it's given back.
        conversation.state = HUMAN_HANDOFF
        created = Escalation(
            business_id=business.id, conversation_id=conversation.id, message_id=bot_message.id,
            kind=str(Action.HANDOFF), reason=reason, question=one_line(customer_message.text),
            status="pending",
        )
    if created is not None:
        session.add(created)
    session.flush()
    return bot_message, created


def team_handoff(session: Session, business: Business, conversation: Conversation) -> Escalation | None:
    """The chat's latest complaint or lead: what a contact left in the chat is for."""
    return session.scalar(
        select(Escalation)
        .where(Escalation.business_id == business.id, Escalation.conversation_id == conversation.id,
               Escalation.kind == Action.HANDOFF, Escalation.reason.in_([str(r) for r in TEAM_REASONS]))
        .order_by(Escalation.id.desc())
        .limit(1)
    )


def wants_contact(session: Session, business: Business, conversation: Conversation, settings: dict) -> bool:
    """Whether the chat should offer "leave your email or WhatsApp number": the business asks for
    it, the chat has a complaint or lead, and the customer hasn't left either yet."""
    return bool(settings["ask_contact"] and not (conversation.customer_email or conversation.customer_phone)
                and team_handoff(session, business, conversation) is not None)


def panel_for(decision: BrainDecision, kb: KnowledgeBase) -> dict:
    """What the "Behind the reply" panel may show: public entries only, plus a count of internal ones."""
    public = [c for c in decision.cited_entries if kb.is_public(c)]
    return {
        "action": str(decision.action),
        "question_for_owner": decision.question_for_owner,
        "sources": [
            {"id": c, "text": kb.entries[c].text, "learned": kb.entries[c].status == "learned"} for c in public
        ],
        "internal_rules_used": len(decision.cited_entries) - len(public),
    }


def is_relayed(message: Message) -> bool:
    """A bot message passing on the owner's answer: the only `answer` with no cited entries
    (a real answer must cite one, so the brain can't produce this shape)."""
    return message.role == Role.BOT and message.action == Action.ANSWER and not message.cited_entries


def customer_view(message: Message, contact_line: str | None = None) -> dict:
    """A message as the customer page may see it. `relayed` appears only when true, and
    `contacts` (the business's contact line, in the customer's language) only under replies that
    need a person. The contact line isn't part of the stored text, so the bot never sees it in
    the history and never learns to copy it."""
    view = {"id": message.id, "role": message.role, "text": message.text}
    if is_relayed(message):
        view["relayed"] = True
    if contact_line and message.role == Role.BOT and needs_contacts(message.action, message.handoff_reason):
        view["contacts"] = contact_line
    return view


def messages_after(session: Session, business: Business, conversation: Conversation, after: int) -> list[Message]:
    return session.scalars(
        select(Message)
        .where(Message.business_id == business.id, Message.conversation_id == conversation.id,
               Message.id > after)
        .order_by(Message.id)
    ).all()
