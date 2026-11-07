"""Alerts and the customer side where a business runs for real: who gets an email for each event, the
contact line under replies that need a person, "leave your email" and the answer email, and the
offline fallback when the model can't be reached. Email goes to a RecordingMailer (no Resend).

In-memory SQLite and ScriptedClients: no model is called and the development database is never touched.
"""

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import AppState, Business, Conversation, Escalation, make_engine, make_session_factory
from app.main import Deployment, create_app
from app.services.alerts import OFFLINE_KEY, AlertConfig, classify
from app.services.mail import RecordingMailer
from brain.llm import ScriptedClient

CHAT = "/api/b/the-plug/chat"
OWNER = "/api/owner/the-plug"
SINGLE = Deployment(mode="single", business="the-plug", name="Jawab – The Plug")
ALERTS = AlertConfig(deployment="Jawab – The Plug", owner=["owner@example.com"],
                     shop=["shop@example.com", "manager@example.com"])
CONTACTS_EN = "For anything urgent, call 22 542659 (24/7) or message us on WhatsApp 94 055151."
CONTACTS_EL = "Για κάτι επείγον, πάρε μας στο 22 542659 (24/7) ή στείλε μας μήνυμα στο WhatsApp 94 055151."


def decision(action="ask_owner", reason=None, reply="Let me check with the team and get back to you.", **extra) -> str:
    return json.dumps({
        "reasoning": extra.get("reasoning", "The KB doesn't cover holidays."),
        "action": action,
        "handoff_reason": reason,
        "reply": reply,
        "cited_entries": extra.get("cited", ["shop-hours"] if action == "answer" else []),
        "question_for_owner": "Are we open on Christmas Day?" if action == "ask_owner" else None,
    })


def learn(reply="We're closed on 25 December.") -> str:
    return json.dumps({"reasoning": "A general fact.", "reply_to_customer": reply, "learn_action": "none",
                       "target_entry_id": None, "proposed_entry": None, "owner_summary": "Nothing to save."})


class Broken:
    """A model client whose provider fails, like the OpenAI SDK's errors."""

    model = "gpt-test"

    def __init__(self, error: Exception):
        self.error = error

    def complete(self, system, messages, schema):
        raise self.error


class QuotaError(Exception):
    status_code = 429
    code = "insufficient_quota"


@pytest.fixture
def make():
    def _make(*responses, client=None, deployment=SINGLE):
        engine = make_engine("sqlite://")
        mailer = RecordingMailer()
        app = create_app(engine, client or ScriptedClient(list(responses)), deployment=deployment,
                         mailer=mailer, alert_config=AlertConfig(deployment.name, ALERTS.owner, ALERTS.shop))
        sessions = make_session_factory(engine)
        with sessions() as session:
            key = session.scalar(select(Business.owner_key).where(Business.slug == "the-plug"))
        return TestClient(app), mailer, sessions, {"X-Owner-Key": key}
    return _make


def say(client, message, conversation_id=None, lang=None):
    response = client.post(CHAT, json={"conversation_id": conversation_id, "message": message, "lang": lang})
    return response


# --- Routing per event ---------------------------------------------------------------------------


def test_ask_owner_emails_the_owner_once_with_a_link_but_no_key(make):
    client, mailer, _, headers = make(decision(), decision())
    first = say(client, "Είστε ανοιχτά τα Χριστούγεννα;").json()
    assert first["contacts"] == CONTACTS_EL  # the customer wrote in Greek
    assert first["ask_email"] is True
    assert len(mailer.sent) == 1
    email = mailer.sent[0]
    assert email["to"] == ["owner@example.com"]
    assert email["subject"].startswith("[Jawab – The Plug] New question: Are we open on Christmas Day?")
    assert "Greek" in email["text"] and "http://testserver/owner/the-plug" in email["text"]
    assert headers["X-Owner-Key"] not in email["text"]
    # The customer adds a detail: the same pending question, so no second email.
    say(client, "Και στις 26;", first["conversation_id"])
    assert len(mailer.sent) == 1


@pytest.mark.parametrize("reason,subject", [("complaint", "[Jawab – Complaint]"), ("lead", "[Jawab – Lead]")])
def test_complaints_and_leads_email_the_shop(make, reason, subject):
    client, mailer, _, _ = make(decision("handoff", reason, "I'm passing this to the team.",
                                         reasoning="The customer wants a refund for a misprinted poster."))
    data = say(client, "You ruined my poster, I want my money back").json()
    assert data["state"] == "human_handoff"
    assert data["contacts"] == CONTACTS_EN
    assert data["ask_email"] is False
    assert len(mailer.sent) == 1
    email = mailer.sent[0]
    assert email["to"] == ["shop@example.com", "manager@example.com"]
    assert email["subject"].startswith(subject)
    assert "Summary: The customer wants a refund for a misprinted poster." in email["text"]
    assert "Customer: You ruined my poster, I want my money back" in email["text"]
    assert "Assistant: I'm passing this to the team." in email["text"]
    assert "Customer's email: not given" in email["text"]


def test_other_handoffs_email_nobody_but_show_the_contacts(make):
    client, mailer, sessions, _ = make(decision("handoff", "other", "A team member will help you."))
    data = say(client, "I think I left my USB stick there yesterday").json()
    assert data["state"] == "human_handoff" and data["contacts"] == CONTACTS_EN
    assert mailer.sent == []
    with sessions() as session:
        assert session.scalar(select(Escalation)).status == "pending"  # still in the owner's inbox


def test_abuse_gets_only_the_goodbye_and_the_chat_ends(make):
    client, mailer, sessions, headers = make(decision("handoff", "abuse", "Sorry you feel that way. Take care."))
    data = say(client, "you're all idiots").json()
    assert data["state"] == "ended"
    assert data["contacts"] is None
    assert mailer.sent == []
    # Nobody needs to act: recorded, but closed straight away.
    with sessions() as session:
        escalation = session.scalar(select(Escalation))
        assert (escalation.kind, escalation.reason, escalation.status) == ("handoff", "abuse", "closed")
    card = client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"][0]
    assert card["reason"] == "abuse" and card["status"] == "closed"
    # More of the same costs no model call (the ScriptedClient has nothing left) and gets no reply.
    again = say(client, "idiots", data["conversation_id"]).json()
    assert again["message"] is None and again["state"] == "ended"


def test_the_public_demo_sends_no_alerts_and_shows_no_real_contacts(make):
    client, mailer, _, _ = make(decision(), decision("handoff", "complaint", "Passing you on."), deployment=Deployment())
    asked = say(client, "Are you open on Christmas?").json()
    assert asked["contacts"] is None and asked["ask_email"] is False
    complained = say(client, "My prints are wrong, refund please").json()
    assert complained["contacts"] is None
    assert mailer.sent == []


def test_the_contact_line_comes_back_with_the_conversation(make):
    client, _, _, _ = make(decision())
    data = say(client, "Are you open on Christmas?", lang="el").json()
    # Latin text on a Greek page: the page's language.
    messages = client.get(f"/api/b/the-plug/conversations/{data['conversation_id']}/messages").json()
    bot = [m for m in messages["messages"] if m["role"] == "bot"][0]
    assert bot["contacts"] == CONTACTS_EL
    assert messages["email_capture"] is True and messages["email_saved"] is False
    # The contact line isn't part of the stored reply, so the bot never sees it in its history.
    assert "22 542659" not in bot["text"]


# --- "Leave your email", and the answer by email ---------------------------------------------------


def test_the_owners_answer_is_emailed_to_the_customer_in_their_language(make):
    arabic_reply = "نحن مغلقون يوم ٢٥ ديسمبر."
    client, mailer, sessions, headers = make(decision(), learn(arabic_reply))
    data = say(client, "هل أنتم مفتوحون يوم عيد الميلاد؟").json()
    conversation = data["conversation_id"]
    email_url = f"/api/b/the-plug/conversations/{conversation}/email"
    assert client.post(email_url, json={"email": "not an email"}).status_code == 422
    assert client.post(email_url, json={"email": "customer@example.com"}).json() == {"ok": True}
    assert client.get(f"/api/b/the-plug/conversations/{conversation}/messages").json()["email_saved"] is True

    card = client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"][0]
    assert card["customer_email"] == "customer@example.com" and card["customer_language"] == "ar"
    mailer.sent.clear()  # the ask_owner alert
    answered = client.post(f"{OWNER}/escalations/{card['id']}/answer", headers=headers,
                           json={"text": "Closed on the 25th."})
    assert answered.status_code == 200
    assert len(mailer.sent) == 1
    email = mailer.sent[0]
    assert email["to"] == ["customer@example.com"]
    assert email["subject"] == "سؤالك إلى The Plug"
    assert arabic_reply in email["text"] and "هل أنتم مفتوحون يوم عيد الميلاد؟" in email["text"]
    assert "94 055151" in email["text"]  # the contact line, in Arabic
    assert email["reply_to"] == "theplug.cyprus@gmail.com"
    # It's in the chat too, as before.
    messages = client.get(f"/api/b/the-plug/conversations/{conversation}/messages").json()["messages"]
    assert messages[-1]["text"] == arabic_reply and messages[-1].get("relayed")


def test_no_email_is_sent_without_an_address(make):
    client, mailer, _, headers = make(decision(), learn())
    say(client, "Are you open on Christmas?")
    card = client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"][0]
    mailer.sent.clear()
    client.post(f"{OWNER}/escalations/{card['id']}/answer", headers=headers, json={"text": "Closed."})
    assert mailer.sent == []


def test_an_email_needs_a_question_and_a_business_that_emails(make):
    client, _, _, _ = make(decision("answer", reply="We're open 24/7."))
    conversation = say(client, "Are you open now?").json()["conversation_id"]
    url = f"/api/b/the-plug/conversations/{conversation}/email"
    assert client.post(url, json={"email": "a@example.com"}).status_code == 409  # nothing was asked
    demo, _, _, _ = make(decision(), deployment=Deployment())
    asked = say(demo, "Christmas?").json()["conversation_id"]
    # The public demo never collects addresses: a visitor could make the shop's domain email anyone.
    assert demo.post(f"/api/b/the-plug/conversations/{asked}/email", json={"email": "a@example.com"}).status_code == 404


# --- Offline fallback ----------------------------------------------------------------------------


def test_out_of_credit_shows_the_offline_message_and_tells_the_owner_once(make):
    client, mailer, sessions, _ = make(client=Broken(QuotaError("You exceeded your current quota")))
    response = say(client, "Γεια, είστε ανοιχτά;")
    assert response.status_code == 503
    body = response.json()
    assert body["offline"] is True
    assert body["detail"].startswith("Η συνομιλία δεν είναι διαθέσιμη αυτή τη στιγμή. Πάρε μας τηλέφωνο στο 22 542659")
    assert "Traceback" not in response.text and "quota" not in body["detail"]
    assert len(mailer.sent) == 1
    alert = mailer.sent[0]
    assert alert["to"] == ["owner@example.com"]
    assert alert["subject"] == "[Jawab – The Plug] Out of OpenAI credit: the chat is offline"
    assert "insufficient_quota" in alert["text"] and "Both deployments share one OpenAI balance" in alert["text"]

    # Within 6 hours: the offline message again, but no second email.
    assert say(client, "Hello?").status_code == 503
    assert len(mailer.sent) == 1
    # After 6 hours, one more.
    with sessions() as session:
        row = session.get(AppState, OFFLINE_KEY)
        from datetime import datetime
        row.value = (datetime.fromisoformat(row.value) - timedelta(hours=7)).isoformat()
        session.commit()
    say(client, "Anyone?")
    assert len(mailer.sent) == 2


def test_the_demo_shows_its_own_offline_message(make):
    client, mailer, _, _ = make(client=Broken(TimeoutError("timed out")), deployment=Deployment(name="Jawab demo"))
    body = say(client, "hi").json()
    assert body["detail"] == "The demo is offline for a moment. Please try again later."
    # The offline alert belongs to the deployment, so the demo sends it too.
    assert mailer.sent and mailer.sent[0]["subject"] == "[Jawab demo] The chat is offline"


class Status(Exception):
    def __init__(self, status_code, code=None):
        super().__init__(f"error {status_code}")
        self.status_code, self.code = status_code, code


class APITimeoutError(Exception):
    pass


@pytest.mark.parametrize("error,cause", [
    (Status(429, "insufficient_quota"), "no_credit"),
    (Status(429, "rate_limit_exceeded"), "rate_limited"),
    (Status(401), "key_rejected"),
    (Status(403), "key_rejected"),
    (Status(503), "provider_down"),
    (APITimeoutError(), "provider_down"),
    (ValueError("something else"), "other"),
])
def test_why_the_model_failed(error, cause):
    assert classify(error) == cause


def test_the_customer_message_is_kept_when_the_model_fails(make):
    client, _, sessions, _ = make(client=Broken(Status(500)))
    say(client, "Do you print posters?")
    with sessions() as session:
        conversation = session.scalar(select(Conversation))
        assert conversation.language == "en"
