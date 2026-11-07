"""The owner dashboard API (spec section 7), on an in-memory SQLite database with a ScriptedClient.

No model is called and the development database is never touched.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Business, Conversation, Escalation, Message, make_engine, make_session_factory
from app.main import create_app
from brain.llm import ScriptedClient

CHAT = "/api/b/the-plug/chat"
OWNER = "/api/owner/the-plug"
QUESTION = "Are we open on Christmas Day (25 December)?"
OWNER_ANSWER = "We're closed on 25 December, back to 24/7 on the 26th."
ARABIC_REPLY = "نحن مغلقون يوم ٢٥ ديسمبر، ونعود للعمل على مدار الساعة من يوم ٢٦."


def decision(**overrides) -> str:
    fields = {
        "reasoning": "The KB doesn't cover holidays.",
        "action": "ask_owner",
        "reply": "دعني أتحقق من الفريق وأعود إليك.",
        "cited_entries": [],
        "question_for_owner": QUESTION,
    }
    if "handoff_reason" not in overrides:
        overrides["handoff_reason"] = "other" if overrides.get("action") == "handoff" else None
    return json.dumps({**fields, **overrides})


def learn(**overrides) -> str:
    fields = {
        "reasoning": "Christmas closing applies to every customer, so it's worth saving.",
        "reply_to_customer": ARABIC_REPLY,
        "learn_action": "add",
        "target_entry_id": None,
        "proposed_entry": {"id": "holiday-christmas", "visibility": "public",
                           "text": "Closed on 25 December. Open 24/7 again from 26 December."},
        "owner_summary": "Save: closed on 25 December, back to 24/7 on the 26th.",
    }
    return json.dumps({**fields, **overrides})


@pytest.fixture
def make():
    """Returns (TestClient, ScriptedClient, session factory, owner headers)."""
    def _make(*responses):
        engine = make_engine("sqlite://")
        scripted = ScriptedClient(list(responses))
        app = create_app(engine, scripted)
        sessions = make_session_factory(engine)
        with sessions() as session:
            key = session.scalar(select(Business.owner_key).where(Business.slug == "the-plug"))
        return TestClient(app), scripted, sessions, {"X-Owner-Key": key}
    return _make


def pending_escalation(client, headers, kind):
    escalations = client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"]
    return next(e for e in escalations if e["kind"] == kind and e["status"] == "pending")


def test_answering_ask_owner_relays_the_reply_and_stores_the_proposal(make):
    client, scripted, sessions, headers = make(decision(), learn())
    chat = client.post(CHAT, json={"message": "هل أنتم مفتوحون يوم عيد الميلاد؟"}).json()
    assert chat["state"] == "waiting_on_owner"

    card = pending_escalation(client, headers, "ask_owner")
    assert card["question"] == QUESTION
    assert [m["role"] for m in card["messages"]] == ["customer", "bot"]
    assert card["messages"][1]["action"] == "ask_owner"
    assert "reasoning" not in json.dumps(card["messages"])

    response = client.post(f"{OWNER}/escalations/{card['id']}/answer", json={"text": OWNER_ANSWER}, headers=headers)
    assert response.status_code == 200
    answered = response.json()["escalation"]
    assert answered["status"] == "answered"
    assert answered["conversation_state"] == "bot_active"
    assert answered["relay"]["fallback"] is False
    assert answered["relay"]["sent_text"] == ARABIC_REPLY
    assert answered["relay"]["proposal"]["proposed_entry"]["id"] == "holiday-christmas"

    # The learn call got the prompt, the KB, the conversation, the question and the owner's answer.
    system, messages, schema = scripted.calls[1]
    assert system.startswith("# Role")
    content = messages[0]["content"]
    for tag in ("knowledge_base", "conversation", "question_for_owner", "owner_answer"):
        assert f"<{tag}>" in content
    assert "[customer] هل أنتم مفتوحون" in content and "[bot, ask_owner]" in content
    assert OWNER_ANSWER in content and QUESTION in content
    assert schema["title"] == "LearnResult"

    # The customer's open chat gets the reply as a bot message, and the state is back to bot_active.
    polled = client.get(f"/api/b/the-plug/conversations/{chat['conversation_id']}/messages?after=0").json()
    assert polled["state"] == "bot_active"
    assert polled["messages"][-1] == {"id": polled["messages"][-1]["id"], "role": "bot", "text": ARABIC_REPLY,
                                     "relayed": True}  # marked as the owner's answer

    with sessions() as session:
        escalation = session.scalar(select(Escalation))
        assert escalation.status == "answered"
        assert escalation.owner_answer == OWNER_ANSWER
        assert escalation.answered_at is not None
        assert escalation.learn_proposal["learn_action"] == "add"
        assert escalation.learn_proposal["owner_summary"].startswith("Save:")
        assert escalation.learn_decision is None  # nothing is saved to the KB in this phase
        bot = session.scalars(select(Message).where(Message.role == "bot").order_by(Message.id)).all()[-1]
        assert bot.action == "answer" and bot.text == ARABIC_REPLY
        business = session.scalar(select(Business))
        assert business.kb_version == 1 and "holiday-christmas" not in business.kb_markdown

    # A second answer to the same question is refused, without a model call.
    again = client.post(f"{OWNER}/escalations/{card['id']}/answer", json={"text": "again"}, headers=headers)
    assert again.status_code == 409
    assert len(scripted.calls) == 2


def test_learn_checks_fix_a_taken_id_and_retry_bad_text(make):
    bad = learn(proposed_entry={"id": "shop-hours", "visibility": "public", "text": "## Holidays\nClosed 25 Dec."})
    client, scripted, sessions, headers = make(decision(), bad, learn(proposed_entry={
        "id": "shop-hours", "visibility": "public", "text": "Closed on 25 December."}))
    client.post(CHAT, json={"message": "Open on Christmas?"})
    card = pending_escalation(client, headers, "ask_owner")
    answered = client.post(f"{OWNER}/escalations/{card['id']}/answer", json={"text": OWNER_ANSWER},
                           headers=headers).json()["escalation"]

    assert len(scripted.calls) == 3  # one corrective retry
    assert "line starting with '#'" in scripted.calls[2][1][-1]["content"]
    assert answered["relay"]["proposal"]["proposed_entry"]["id"] == "shop-hours-2"  # 'add' needs a new ID


def test_two_invalid_learn_outputs_fall_back_to_a_staff_message(make):
    client, scripted, sessions, headers = make(decision(), "not json", learn(learn_action="update",
                                                                             target_entry_id="no-such-entry"))
    chat = client.post(CHAT, json={"message": "Open on Christmas?"}).json()
    card = pending_escalation(client, headers, "ask_owner")
    response = client.post(f"{OWNER}/escalations/{card['id']}/answer", json={"text": OWNER_ANSWER}, headers=headers)

    assert response.status_code == 200
    relay = response.json()["escalation"]["relay"]
    assert relay == {"fallback": True, "sent_as": "staff", "sent_text": OWNER_ANSWER, "proposal": None,
                     "old_text": None}
    assert len(scripted.calls) == 3
    polled = client.get(f"/api/b/the-plug/conversations/{chat['conversation_id']}/messages?after=0").json()
    assert polled["state"] == "bot_active"
    assert polled["messages"][-1]["role"] == "staff" and polled["messages"][-1]["text"] == OWNER_ANSWER
    with sessions() as session:
        escalation = session.scalar(select(Escalation))
        assert escalation.status == "answered" and escalation.learn_proposal is None


def test_a_null_reply_sends_nothing_to_the_customer(make):
    client, _, sessions, headers = make(decision(), learn(reply_to_customer=None, learn_action="none",
                                                          proposed_entry=None, owner_summary="Nothing to save."))
    client.post(CHAT, json={"message": "Open on Christmas?"})
    card = pending_escalation(client, headers, "ask_owner")
    answered = client.post(f"{OWNER}/escalations/{card['id']}/answer", json={"text": "note to Ali: check stock"},
                           headers=headers).json()["escalation"]
    assert answered["relay"]["sent_text"] is None and answered["relay"]["sent_as"] is None
    with sessions() as session:
        assert [m.role for m in session.scalars(select(Message).order_by(Message.id))] == ["customer", "bot"]


def test_owner_key_is_required(make):
    client, _, _, headers = make()
    assert client.get(f"{OWNER}/escalations").status_code == 403
    assert client.get(f"{OWNER}/escalations", headers={"X-Owner-Key": "wrong"}).status_code == 403
    assert client.get(f"{OWNER}/stats?key=wrong").status_code == 403
    assert client.get(f"{OWNER}/knowledge", params={"key": "ключ"}).status_code == 403  # non-ASCII is fine
    assert client.post(f"{OWNER}/escalations/1/answer", json={"text": "hi"}).status_code == 403
    assert client.post(f"{OWNER}/escalations/1/reply", json={"text": "hi"}).status_code == 403
    assert client.post(f"{OWNER}/escalations/1/give-back").status_code == 403

    assert client.get(f"{OWNER}/escalations", headers=headers).status_code == 200
    assert client.get(f"{OWNER}/stats?key={headers['X-Owner-Key']}").status_code == 200
    assert client.get("/api/owner/nope/stats", headers=headers).status_code == 404
    assert client.get("/owner/the-plug").status_code == 200
    assert client.get("/owner/nope").status_code == 404


def test_handoff_reply_and_give_back(make):
    handoff = decision(action="handoff", reply="I'm passing this to the team.", question_for_owner=None)
    answer = decision(action="answer", reply="We're open 24/7.", cited_entries=["shop-hours"], question_for_owner=None)
    client, scripted, sessions, headers = make(handoff, answer)
    chat = client.post(CHAT, json={"message": "can I speak to a real person"}).json()
    conversation = chat["conversation_id"]
    card = pending_escalation(client, headers, "handoff")

    # The answer route is only for questions; the reply route only for handed-off chats.
    assert client.post(f"{OWNER}/escalations/{card['id']}/answer", json={"text": "hi"},
                       headers=headers).status_code == 409
    assert client.post(f"{OWNER}/escalations/{card['id']}/reply", json={"text": ""},
                       headers=headers).status_code == 422
    assert client.post(f"{OWNER}/escalations/{card['id']}/reply", json={"text": "x" * 1001},
                       headers=headers).status_code == 422

    reply = client.post(f"{OWNER}/escalations/{card['id']}/reply", json={"text": "Hi, Zein here, how can I help?"},
                        headers=headers)
    assert reply.status_code == 200
    assert reply.json()["escalation"]["messages"][-1]["role"] == "staff"
    polled = client.get(f"/api/b/the-plug/conversations/{conversation}/messages?after=0").json()
    assert polled["state"] == "human_handoff"
    assert polled["messages"][-1] == {"id": polled["messages"][-1]["id"], "role": "staff",
                                      "text": "Hi, Zein here, how can I help?"}

    # The customer writes again: it shows up in the owner's card, and the bot stays quiet.
    quiet = client.post(CHAT, json={"conversation_id": conversation, "message": "I need 500 flyers"}).json()
    assert quiet["message"] is None
    card = pending_escalation(client, headers, "handoff")
    assert card["messages"][-1]["text"] == "I need 500 flyers"
    assert len(scripted.calls) == 1

    back = client.post(f"{OWNER}/escalations/{card['id']}/give-back", headers=headers)
    assert back.status_code == 200
    assert back.json()["escalation"]["status"] == "closed"
    assert back.json()["escalation"]["conversation_state"] == "bot_active"
    assert client.post(f"{OWNER}/escalations/{card['id']}/give-back", headers=headers).status_code == 409
    assert client.post(f"{OWNER}/escalations/{card['id']}/reply", json={"text": "hi"},
                       headers=headers).status_code == 409

    # The next customer message gets a bot reply again.
    next_reply = client.post(CHAT, json={"conversation_id": conversation, "message": "are you open?"}).json()
    assert next_reply["message"]["text"] == "We're open 24/7."
    assert len(scripted.calls) == 2
    with sessions() as session:
        assert session.scalar(select(Conversation)).state == "bot_active"
    assert client.post(f"{OWNER}/escalations/999/give-back", headers=headers).status_code == 404


def test_escalation_list_stats_and_knowledge(make):
    answer = decision(action="answer", reply="We're open 24/7.", cited_entries=["shop-hours"], question_for_owner=None)
    client, _, _, headers = make(answer, decision(), decision(action="handoff", reply="Passing you on.",
                                                              question_for_owner=None), learn())
    client.post(CHAT, json={"message": "are you open?"})
    client.post(CHAT, json={"message": "Open on Christmas?"})
    client.post(CHAT, json={"message": "I want a refund"})

    escalations = client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"]
    assert [(e["kind"], e["status"]) for e in escalations] == [("handoff", "pending"), ("ask_owner", "pending")]
    stats = client.get(f"{OWNER}/stats", headers=headers).json()
    assert stats == {"messages_this_week": 3, "answered_by_bot_pct": 33, "questions_learned": 0, "pending": 2}

    ask = escalations[1]
    client.post(f"{OWNER}/escalations/{ask['id']}/answer", json={"text": OWNER_ANSWER}, headers=headers)
    escalations = client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"]
    assert [(e["kind"], e["status"]) for e in escalations] == [("handoff", "pending"), ("ask_owner", "answered")]
    # The relayed reply is the owner's work: it doesn't count as the bot answering on its own.
    stats = client.get(f"{OWNER}/stats", headers=headers).json()
    assert stats == {"messages_this_week": 3, "answered_by_bot_pct": 33, "questions_learned": 0, "pending": 1}

    kb = client.get(f"{OWNER}/knowledge", headers=headers).json()
    assert kb["name"] == "The Plug Mini Market and Print Shop"
    titles = [s["title"] for s in kb["sections"]]
    assert titles[0] == "Shop basics"
    shop = kb["sections"][0]["entries"]
    assert shop[0]["id"] == "shop-hours" and shop[0]["visibility"] == "public"
    assert any(e["visibility"] == "internal" for s in kb["sections"] for e in s["entries"])
    assert sum(len(s["entries"]) for s in kb["sections"]) == kb["entry_count"]


def test_relayed_answers_are_marked_for_the_customer_page(make):
    client, _, _, headers = make(decision(), learn())
    chat = client.post(CHAT, json={"message": "هل أنتم مفتوحون يوم عيد الميلاد؟"}).json()
    card = pending_escalation(client, headers, "ask_owner")
    client.post(f"{OWNER}/escalations/{card['id']}/answer", json={"text": OWNER_ANSWER}, headers=headers)

    messages = client.get(f"/api/b/the-plug/conversations/{chat['conversation_id']}/messages").json()["messages"]
    assert [m["role"] for m in messages] == ["customer", "bot", "bot"]
    # The bot's own "let me check" isn't relayed; the owner's answer passed on by the bot is.
    assert "relayed" not in messages[1]
    assert messages[2]["relayed"] is True and messages[2]["text"] == ARABIC_REPLY
    assert "relayed" not in messages[0]
