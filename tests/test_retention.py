"""Chat retention (D-016): conversations go after a business's retention_days without activity."""

from datetime import timedelta

from sqlalchemy import func, select

from app.db import AppState, Business, Conversation, Escalation, Message, make_engine, make_session_factory, utcnow
from app.main import create_app
from app.services import retention
from app.services.settings import effective
from brain.llm import ScriptedClient


def setup():
    engine = make_engine("sqlite://")
    create_app(engine, ScriptedClient([]))  # creates the tables and seeds The Plug
    return make_session_factory(engine)


def add_chat(session, business: Business, last_activity_days_ago: int, with_escalation: bool = False) -> Conversation:
    when = utcnow() - timedelta(days=last_activity_days_ago)
    conversation = Conversation(business_id=business.id, created_at=when, updated_at=when)
    session.add(conversation)
    session.flush()
    message = Message(business_id=business.id, conversation_id=conversation.id, role="customer",
                      text="Are you open?", created_at=when)
    session.add(message)
    session.flush()
    if with_escalation:
        session.add(Escalation(business_id=business.id, conversation_id=conversation.id, message_id=message.id,
                               kind="ask_owner", question="Open on Christmas?", created_at=when))
    return conversation


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_the_plug_keeps_chats_for_180_days():
    sessions = setup()
    with sessions() as session:
        plug = session.scalar(select(Business).where(Business.slug == "the-plug"))
        assert effective(plug)["retention_days"] == 180


def test_old_chats_go_with_their_messages_and_escalations_recent_ones_stay():
    sessions = setup()
    with sessions() as session:
        plug = session.scalar(select(Business).where(Business.slug == "the-plug"))
        old = add_chat(session, plug, 181, with_escalation=True)
        recent = add_chat(session, plug, 179, with_escalation=True)
        session.commit()
        old_id, recent_id = old.id, recent.id

        assert retention.purge_expired(session) == 1
        session.commit()
        assert session.get(Conversation, old_id) is None
        assert session.get(Conversation, recent_id) is not None
        assert count(session, Message) == 1 and count(session, Escalation) == 1


def test_a_business_without_retention_keeps_everything():
    sessions = setup()
    with sessions() as session:
        other = Business(slug="other", name="Other shop", owner_key="k" * 24, kb_markdown="# Other", settings={})
        session.add(other)
        session.flush()
        add_chat(session, other, 3650)
        session.commit()
        assert retention.purge_expired(session) == 0
        assert count(session, Conversation) == 1


def test_it_runs_at_most_every_few_hours_and_remembers_across_restarts():
    sessions = setup()  # startup already ran it once
    with sessions() as session:
        assert session.scalar(select(AppState).where(AppState.key == retention.LAST_RUN_KEY)) is not None
        plug = session.scalar(select(Business).where(Business.slug == "the-plug"))
        add_chat(session, plug, 400)
        session.commit()

    assert retention.run_if_due(sessions) is None  # too soon after startup's run
    later = utcnow() + retention.RUN_EVERY + timedelta(minutes=1)
    assert retention.run_if_due(sessions, now=later) == 1
    assert retention.run_if_due(sessions, now=later + timedelta(minutes=5)) is None
