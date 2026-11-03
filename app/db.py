"""Database: SQLAlchemy engine, session factory, models, table creation and startup seeding.

Spec section 4. Every table except `businesses` carries `business_id`, and every query filters by
it. Seeding runs in app code at startup because the published app has its own production database.
"""

import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid, create_engine, event, select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from brain.kb import parse_kb

ROOT = Path(__file__).resolve().parent.parent

log = logging.getLogger("jawab.db")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_key: Mapped[str] = mapped_column(Text, nullable=False)
    kb_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    kb_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    suggestions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # A visitor's private copy of a demo business ("Try it as the owner"): the seed's slug. None for
    # real businesses. Sandboxes are deleted after a day (app/services/sandbox.py).
    sandbox_of: Mapped[str | None] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class KBChange(Base):
    __tablename__ = "kb_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    entry_id: Mapped[str | None] = mapped_column(Text)
    change: Mapped[str] = mapped_column(String, nullable=False)  # add, update, manual_edit, initial
    old_text: Mapped[str | None] = mapped_column(Text)
    new_text: Mapped[str | None] = mapped_column(Text)
    source_escalation_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="bot_active")
    language: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # customer, bot, staff
    text: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str | None] = mapped_column(String)  # bot messages only
    cited_entries: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # never sent in full
    reasoning: Mapped[str | None] = mapped_column(Text)  # owner page only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # ask_owner, handoff
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending, answered, closed
    owner_answer: Mapped[str | None] = mapped_column(Text)
    learn_proposal: Mapped[dict | None] = mapped_column(JSON)
    learn_decision: Mapped[str | None] = mapped_column(String)  # saved, edited, once
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Engine -------------------------------------------------------------------------------------


class OnboardingSession(Base):
    """One /start session: the interview so far, then the draft, then the business once published.
    No business_id until it's published (spec section 4)."""

    __tablename__ = "onboarding_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    business_name: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False)  # quick, full
    transcript: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # [{role, text}]
    covered: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # topic IDs
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    draft_kb: Mapped[str | None] = mapped_column(Text)
    open_questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id"))
    # +1 on every saved interview turn. A turn is only saved if nobody saved one meanwhile, since the
    # model call runs outside any transaction (two tabs, a double click).
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


def make_engine(url: str) -> Engine:
    """Engine for a database URL. Postgres URLs keep everything as provided; only the driver name
    is set, so SQLAlchemy uses psycopg 3. `sqlite://` (in memory) is for tests; a SQLite file
    (`sqlite:///jawab.db`) is for a demo server whose data may vanish on restart."""
    if url.startswith("sqlite"):
        in_memory = url in ("sqlite://", "sqlite:///:memory:")
        # In memory: one shared connection, or every connection would see its own empty database.
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 15},
                               **({"poolclass": StaticPool} if in_memory else {}))

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
            if not in_memory:
                dbapi_connection.execute("PRAGMA journal_mode=WAL")  # readers don't wait for a writer

        return engine
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
            break
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


# --- Seeding ------------------------------------------------------------------------------------

# Seed businesses, created once if missing. The data lives here and in kb/; the code that uses it
# is generic.
SEED_BUSINESSES = [
    {
        "slug": "the-plug",
        "kb_path": ROOT / "kb" / "the-plug.md",
        "owner_key_env": "PLUG_OWNER_KEY",
        "demo": True,  # the owner page offers "Reset demo" (back to this KB, no chats)
        "suggestions": [
            "How much for 100 black & white pages?",
            "Πόσο κοστίζει η εκτύπωση 50 έγχρωμων σελίδων;",
            "هل أنتم مفتوحون يوم عيد الميلاد؟",
            "My prints came out in the wrong order!",
            "ana talib, fi discount?",
        ],
    },
]


def new_owner_key() -> str:
    return secrets.token_urlsafe(18)  # 24 characters


def init_db(engine: Engine, session_factory: sessionmaker[Session]) -> None:
    """Create missing tables, then seed missing businesses. Safe to run on every startup."""
    Base.metadata.create_all(engine)
    for seed in SEED_BUSINESSES:
        seed_business(session_factory, seed)


def seed_business(session_factory: sessionmaker[Session], seed: dict) -> None:
    with session_factory() as session:
        existing = session.scalar(select(Business).where(Business.slug == seed["slug"]))
        if existing is not None:
            # The secret is the source of truth: changing it updates every database on next startup.
            env_key = os.environ.get(seed["owner_key_env"])
            if env_key and env_key != existing.owner_key:
                existing.owner_key = env_key
                session.commit()
                log.info("updated the owner key of %s from %s", seed["slug"], seed["owner_key_env"])
            return
        kb_markdown = Path(seed["kb_path"]).read_text(encoding="utf-8")
        kb = parse_kb(kb_markdown)  # a seed KB must be valid, like every saved KB
        owner_key = os.environ.get(seed["owner_key_env"])
        if not owner_key:
            owner_key = new_owner_key()
            log.warning("%s is not set; generated owner key for %s: %s",
                        seed["owner_key_env"], seed["slug"], owner_key)
        business = Business(
            slug=seed["slug"],
            name=kb.metadata.get("business") or seed["slug"],
            owner_key=owner_key,
            kb_markdown=kb_markdown,
            kb_version=1,
            suggestions=list(seed["suggestions"]),
        )
        session.add(business)
        session.flush()
        session.add(KBChange(business_id=business.id, change="initial", new_text=kb_markdown))
        try:
            session.commit()
            log.info("seeded business %s", seed["slug"])
        except IntegrityError:
            session.rollback()  # another process seeded it at the same moment
