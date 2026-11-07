"""The customer chat API (spec section 6), on an in-memory SQLite database with a ScriptedClient.

No model is called and the development database is never touched.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import Business, Conversation, Escalation, KBChange, Message, init_db, make_engine, make_session_factory
from app.limits import RateLimiter
from app.main import create_app
from brain.kb import parse_kb
from brain.llm import ScriptedClient

CHAT = "/api/b/the-plug/chat"
PUBLIC_ENTRY = "shop-hours"
INTERNAL_ENTRY = "policy-effort-pricing"
REASONING = "SECRET-REASONING: the customer looks like a student."


def decision(**overrides) -> str:
    fields = {
        "reasoning": REASONING,
        "action": "answer",
        "reply": "We're open 24 hours a day, 7 days a week.",
        "cited_entries": [PUBLIC_ENTRY, INTERNAL_ENTRY],
        "question_for_owner": None,
    }
    if "handoff_reason" not in overrides:
        overrides["handoff_reason"] = "other" if overrides.get("action") == "handoff" else None
    return json.dumps({**fields, **overrides})


@pytest.fixture
def make():
    """Build an app on a fresh in-memory database. Returns (TestClient, ScriptedClient, session factory)."""
    def _make(*responses, limiter=None):
        engine = make_engine("sqlite://")
        scripted = ScriptedClient(list(responses))
        app = create_app(engine, scripted, limiter)
        return TestClient(app), scripted, make_session_factory(engine)
    return _make


def test_chat_answer_returns_only_customer_safe_fields(make):
    client, scripted, sessions = make(decision())
    response = client.post(CHAT, json={"conversation_id": None, "message": "Are you open now?"})

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"conversation_id", "state", "message", "panel", "contacts", "ask_email"}
    assert data["contacts"] is None and data["ask_email"] is False  # an answer needs neither
    assert data["state"] == "bot_active"
    assert set(data["message"]) == {"id", "role", "text", "action"}
    assert data["message"]["role"] == "bot"
    assert data["message"]["action"] == "answer"
    assert data["panel"]["action"] == "answer"
    assert data["panel"]["question_for_owner"] is None
    assert data["panel"]["internal_rules_used"] == 1

    kb = parse_kb(open("kb/the-plug.md", encoding="utf-8").read())
    assert data["panel"]["sources"] == [
        {"id": PUBLIC_ENTRY, "text": kb.entries[PUBLIC_ENTRY].text, "learned": False}
    ]
    # Nothing internal leaves the server: not the internal entry's ID or text, not the reasoning.
    body = response.text
    assert INTERNAL_ENTRY not in body
    assert kb.entries[INTERNAL_ENTRY].text[:60] not in body
    assert "SECRET-REASONING" not in body
    assert len(scripted.calls) == 1

    # But the bot message keeps all of it for the owner.
    with sessions() as session:
        bot = session.scalar(select(Message).where(Message.role == "bot"))
        assert bot.cited_entries == [PUBLIC_ENTRY, INTERNAL_ENTRY]
        assert bot.reasoning == REASONING

    # The messages endpoint is customer-safe too.
    messages = client.get(f"/api/b/the-plug/conversations/{data['conversation_id']}/messages?after=0")
    assert messages.status_code == 200
    assert [m["role"] for m in messages.json()["messages"]] == ["customer", "bot"]
    assert all(set(m) == {"id", "role", "text"} for m in messages.json()["messages"])
    assert "SECRET-REASONING" not in messages.text and INTERNAL_ENTRY not in messages.text


def test_history_comes_from_the_database(make):
    client, scripted, _ = make(decision(), decision(reply="Yes, still open."))
    first = client.post(CHAT, json={"message": "Are you open?"}).json()
    client.post(CHAT, json={"conversation_id": first["conversation_id"], "message": "And at 3am?"})

    user_content = json.dumps(scripted.calls[1][1])
    assert "Are you open?" in user_content and "And at 3am?" in user_content


def test_ask_owner_updates_one_pending_escalation(make):
    ask = dict(action="ask_owner", reply="Let me check with the owner.", cited_entries=[])
    client, _, sessions = make(decision(**ask, question_for_owner="Open on Christmas?"),
                               decision(**ask, question_for_owner="Open on Christmas and Boxing Day?"))
    first = client.post(CHAT, json={"message": "Open on Christmas?"}).json()
    assert first["state"] == "waiting_on_owner"
    assert first["panel"]["question_for_owner"] == "Open on Christmas?"
    client.post(CHAT, json={"conversation_id": first["conversation_id"], "message": "And Boxing Day?"})

    with sessions() as session:
        escalations = session.scalars(select(Escalation)).all()
        assert len(escalations) == 1
        assert escalations[0].kind == "ask_owner"
        assert escalations[0].status == "pending"
        assert escalations[0].question == "Open on Christmas and Boxing Day?"


def test_handoff_stops_the_bot(make):
    client, scripted, sessions = make(decision(action="handoff", reply="I'm passing this to the team.",
                                               cited_entries=[]))
    first = client.post(CHAT, json={"message": "My prints came out in the wrong order!"}).json()
    assert first["state"] == "human_handoff"

    later = client.post(CHAT, json={"conversation_id": first["conversation_id"], "message": "Hello??"})
    assert later.status_code == 200
    assert later.json() == {"conversation_id": first["conversation_id"], "state": "human_handoff",
                            "message": None, "panel": None, "contacts": None, "ask_email": False}
    assert len(scripted.calls) == 1  # the second message never reached the model

    with sessions() as session:
        escalation = session.scalar(select(Escalation))
        assert escalation.kind == "handoff"
        assert "wrong order" in escalation.question
        assert session.scalar(select(func.count()).select_from(Message).where(Message.role == "customer")) == 2


def test_validation_unknown_business_and_rate_limit(make):
    client, scripted, _ = make(decision(), limiter=RateLimiter(per_visitor=1, per_day=100))
    assert client.post(CHAT, json={"message": ""}).status_code == 422
    assert client.post(CHAT, json={"message": "   "}).status_code == 422
    assert client.post(CHAT, json={"message": "x" * 501}).status_code == 422
    assert client.post("/api/b/nope/chat", json={"message": "hi"}).status_code == 404
    assert client.get("/b/nope").status_code == 404

    headers = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}
    assert client.post(CHAT, json={"message": "hi"}, headers=headers).status_code == 200
    assert client.post(CHAT, json={"message": "hi again"}, headers=headers).status_code == 429
    # A different visitor behind the same proxy has their own limit, so this one reaches the model.
    # The ScriptedClient has no responses left, which shows up as the friendly 503 rather than a 429.
    other = client.post(CHAT, json={"message": "hi"}, headers={"X-Forwarded-For": "198.51.100.7"})
    assert other.status_code == 503
    assert len(scripted.calls) == 2


def test_public_info_pages_and_seeding_is_idempotent(make):
    client, _, sessions = make()
    info = client.get("/api/b/the-plug/public").json()
    assert info["name"] == "The Plug"  # the display name; the KB keeps the full one
    assert len(info["suggestions"]) == 5
    assert client.get("/b/the-plug").status_code == 200
    assert client.get("/health").json() == {"ok": True, "model": "scripted"}
    assert "/try" in client.get("/").text

    engine = sessions.kw["bind"]
    init_db(engine, sessions)  # a second startup
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Business)) == 1
        assert session.scalar(select(func.count()).select_from(KBChange)) == 1
        assert session.scalar(select(func.count()).select_from(Conversation)) == 0
