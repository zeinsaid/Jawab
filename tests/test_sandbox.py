"""Sandboxes ("Try it as the owner"): each visitor's private copy of the demo business."""

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.db import Business, Conversation, Escalation, KBChange, Message, make_engine, make_session_factory, utcnow
from app.limits import RateLimiter
from app.main import create_app
from app.services import sandbox
from brain.llm import ScriptedClient


def ask() -> str:
    return json.dumps({
        "reasoning": "The KB doesn't cover this.",
        "action": "ask_owner",
        "handoff_reason": None,
        "reply": "Let me check with the team and get back to you.",
        "cited_entries": [],
        "question_for_owner": "Are we open on Christmas Day?",
    })


def learn() -> str:
    return json.dumps({
        "reasoning": "A general fact.",
        "reply_to_customer": "We're closed on 25 December.",
        "learn_action": "add",
        "target_entry_id": None,
        "proposed_entry": {"id": "holiday-christmas", "visibility": "public", "text": "Closed on 25 December."},
        "owner_summary": "Save: closed on Christmas Day.",
    })


def make(*responses, sandbox_limiter=None):
    engine = make_engine("sqlite://")
    app = create_app(engine, ScriptedClient(list(responses)), sandbox_limiter=sandbox_limiter)
    return TestClient(app), make_session_factory(engine)


def test_a_sandbox_is_a_private_copy_with_its_own_key():
    client, sessions = make()
    first = client.post("/api/sandbox").json()
    second = client.post("/api/sandbox").json()
    assert first["slug"].startswith("try-") and first["slug"] != second["slug"]
    assert first["owner_key"] != second["owner_key"] and len(first["owner_key"]) >= 20
    assert first["owner_url"] == f"/owner/{first['slug']}?key={first['owner_key']}"

    assert client.get(f"/api/b/{first['slug']}/public").json()["name"] == "The Plug Mini Market and Print Shop"
    assert client.get(first["chat_url"]).status_code == 200
    # The other visitor's key doesn't open this inbox.
    wrong = client.get(f"/api/owner/{first['slug']}/escalations", headers={"X-Owner-Key": second["owner_key"]})
    assert wrong.status_code == 403
    # Sandboxes never show in the landing page's numbers.
    assert client.get(f"/api/public-stats/{first['slug']}").status_code == 404


def test_what_one_visitor_teaches_stays_in_their_sandbox():
    client, sessions = make(ask(), learn())
    box = client.post("/api/sandbox").json()
    headers = {"X-Owner-Key": box["owner_key"]}
    client.post(f"/api/b/{box['slug']}/chat", json={"message": "open on christmas?"})
    escalation = client.get(f"/api/owner/{box['slug']}/escalations", headers=headers).json()["escalations"][0]
    client.post(f"/api/owner/{box['slug']}/escalations/{escalation['id']}/answer", json={"text": "Closed."},
                headers=headers)
    saved = client.post(f"/api/owner/{box['slug']}/escalations/{escalation['id']}/learn",
                        json={"decision": "saved"}, headers=headers)
    assert saved.json()["ok"] is True

    with sessions() as session:
        plug = session.scalar(select(Business).where(Business.slug == "the-plug"))
        mine = session.scalar(select(Business).where(Business.slug == box["slug"]))
        assert "holiday-christmas" in mine.kb_markdown
        assert "holiday-christmas" not in plug.kb_markdown
        assert session.scalar(select(func.count()).select_from(Escalation).where(Escalation.business_id == plug.id)) == 0

    # A sandbox can be reset, like the demo business it copies.
    knowledge = client.get(f"/api/owner/{box['slug']}/knowledge", headers=headers).json()
    assert knowledge["can_reset_demo"] is True
    assert client.post(f"/api/owner/{box['slug']}/reset-demo", headers=headers).status_code == 200


def test_expired_sandboxes_are_deleted_with_everything_in_them():
    client, sessions = make(ask())
    old = client.post("/api/sandbox").json()
    client.post(f"/api/b/{old['slug']}/chat", json={"message": "open on christmas?"})
    with sessions() as session:
        session.execute(update(Business).where(Business.slug == old["slug"])
                        .values(created_at=utcnow() - sandbox.LIFETIME - timedelta(minutes=1)))
        session.commit()

    client.post("/api/sandbox")
    with sessions() as session:
        assert session.scalar(select(Business).where(Business.slug == old["slug"])) is None
        for model in (Conversation, Message, Escalation):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.scalar(select(Business).where(Business.slug == "the-plug")) is not None
        live = session.scalar(select(func.count()).select_from(Business).where(Business.sandbox_of.is_not(None)))
        assert live == 1
        assert session.scalar(select(func.count()).select_from(KBChange)) == 2  # the plug + the new one
    assert client.get(f"/api/b/{old['slug']}/public").status_code == 404


def test_sandbox_creation_is_rate_limited():
    client, _ = make(sandbox_limiter=RateLimiter(per_visitor=1, per_day=100))
    assert client.post("/api/sandbox").status_code == 200
    assert client.post("/api/sandbox").status_code == 429


def test_a_full_demo_says_so(monkeypatch):
    monkeypatch.setattr(sandbox, "MAX_LIVE", 1)
    client, _ = make()
    assert client.post("/api/sandbox").status_code == 200
    assert client.post("/api/sandbox").status_code == 503


def test_the_try_page_is_served():
    client, _ = make()
    page = client.get("/try")
    assert page.status_code == 200 and "/static/try.js" in page.text


def test_a_sqlite_file_database_works(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'jawab.db'}")
    client = TestClient(create_app(engine, ScriptedClient([])))
    assert client.post("/api/sandbox").status_code == 200
    assert client.get("/api/b/the-plug/public").status_code == 200


def test_the_demo_shop_offers_english_greek_and_arabic():
    client, _ = make()
    box = client.post("/api/sandbox").json()
    for slug in ("the-plug", box["slug"]):
        info = client.get(f"/api/b/{slug}/public").json()
        assert info["languages"] == ["en", "el", "ar"]
        assert any("Πόσο" in s for s in info["suggestions"])


def test_missing_pages_get_the_styled_page_and_the_api_keeps_json():
    client, _ = make()
    for path in ("/b/nobody-here", "/owner/nobody-here?key=x", "/no-such-page"):
        page = client.get(path)
        assert page.status_code == 404 and "This page isn't here" in page.text and 'href="/try"' in page.text, path
    api = client.get("/api/b/nobody-here/public")
    assert api.status_code == 404 and api.json() == {"detail": "Business not found."}
    assert client.get("/api/no-such-route").json() == {"detail": "Not Found"}
