"""Chat retention: delete a business's conversations after a set time without activity (D-016).

A business that sets `retention_days` in its settings has a conversation deleted once nothing has
happened in it (no message from the customer, the bot or the team) for that many days, together
with its messages and escalations. `None`, the default, keeps conversations. The Plug's privacy page
promises 6 months, so its seed sets 180 days: never longer than promised.

Render's free plan has no scheduler, so the purge runs when the server starts (the free server
wakes up several times a day) and, while it's awake, at most once every RUN_EVERY, after a chat
message. AppState remembers the last run, so restarts don't make it run more often.

Learned knowledge isn't affected: saved answers live in the KB, and a KB change only keeps the
escalation's ID, not the conversation.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import AppState, Business, Conversation, Escalation, Message, utcnow
from app.services.settings import effective

RUN_EVERY = timedelta(hours=6)
LAST_RUN_KEY = "retention:last_run"


def purge_expired(session: Session, now: datetime | None = None) -> int:
    """Delete conversations past their business's retention, children first. Returns how many.
    Doesn't commit."""
    now = now or utcnow()
    removed = 0
    for business in session.scalars(select(Business)):
        days = effective(business).get("retention_days")
        if not days:
            continue
        cutoff = now - timedelta(days=int(days))
        ids = list(session.scalars(select(Conversation.id).where(Conversation.business_id == business.id,
                                                                 Conversation.updated_at < cutoff)))
        if not ids:
            continue
        for model in (Escalation, Message):  # foreign keys: escalation -> message -> conversation
            session.execute(delete(model).where(model.conversation_id.in_(ids)))
        session.execute(delete(Conversation).where(Conversation.id.in_(ids)))
        removed += len(ids)
    return removed


def run_if_due(session_factory: sessionmaker[Session], now: datetime | None = None) -> int | None:
    """Purge if the last run was more than RUN_EVERY ago (or never). Returns how many conversations
    were deleted, or None if it wasn't due."""
    now = now or utcnow()
    with session_factory() as session:
        row = session.scalar(select(AppState).where(AppState.key == LAST_RUN_KEY))
        if row is not None:
            last = datetime.fromisoformat(row.value)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if now - last < RUN_EVERY:
                return None
            row.value = now.isoformat()
        else:
            session.add(AppState(key=LAST_RUN_KEY, value=now.isoformat()))
        removed = purge_expired(session, now)
        session.commit()
        return removed
