"""Sandboxes: "Try it as the owner" for visitors to the public demo.

Each visitor gets a private copy of a demo business (The Plug): its own slug, owner key, inbox and
knowledge base. They chat as a customer and answer as the owner side by side, and what they teach
the bot only exists in their copy, so nobody can plant answers that other visitors would see.

Copies are deleted a day after they're made (checked whenever a new one is made), and there's a cap
on how many exist at once. On the free demo server the whole SQLite database also goes whenever the
server restarts, so this is a second line of defence, not the main one.
"""

import secrets
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import SEED_BUSINESSES, Business, Conversation, Escalation, KBChange, Message, new_owner_key, utcnow
from app.services.settings import seed_settings
from brain.kb import parse_kb

LIFETIME = timedelta(hours=24)
MAX_LIVE = 500  # sandboxes at once; each is one KB copy (about 40 KB) plus its chats


class Full(Exception):
    """Too many sandboxes exist right now."""


def demo_seeds() -> dict[str, dict]:
    return {s["slug"]: s for s in SEED_BUSINESSES if s.get("demo")}


def create(session_factory: sessionmaker[Session], seed_slug: str = "the-plug") -> tuple[Business, list[int]]:
    """Make a fresh copy of a demo business. Returns it and the IDs of expired copies removed."""
    seed = demo_seeds()[seed_slug]
    kb_markdown = Path(seed["kb_path"]).read_text(encoding="utf-8")
    kb = parse_kb(kb_markdown)
    with session_factory() as session:
        removed = purge_expired(session)
        live = session.scalar(select(func.count()).select_from(Business).where(Business.sandbox_of.is_not(None)))
        if live >= MAX_LIVE:
            session.commit()
            raise Full("The demo is very busy right now. Please try again later.")
        business = Business(
            slug=f"try-{secrets.token_hex(5)}",
            name=kb.metadata.get("business") or seed_slug,
            owner_key=new_owner_key(),
            kb_markdown=kb_markdown,
            kb_version=1,
            suggestions=list(seed["suggestions"]),
            sandbox_of=seed_slug,
            demo=True,  # never live: no real contacts, emails or alerts
            settings=seed_settings(seed, demo=True),
        )
        session.add(business)
        session.flush()
        session.add(KBChange(business_id=business.id, change="initial", new_text=kb_markdown))
        session.commit()
        return business, removed


def purge_expired(session: Session) -> list[int]:
    """Delete sandboxes older than LIFETIME, children first (foreign keys). Doesn't commit."""
    cutoff = utcnow() - LIFETIME
    ids = list(session.scalars(select(Business.id).where(Business.sandbox_of.is_not(None),
                                                          Business.created_at < cutoff)))
    if ids:
        for model in (KBChange, Escalation, Message, Conversation):
            session.execute(delete(model).where(model.business_id.in_(ids)))
        session.execute(delete(Business).where(Business.id.in_(ids)))
    return ids
