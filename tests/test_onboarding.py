"""Self-serve onboarding at /start (spec section 8), on an in-memory SQLite database with ScriptedClients.

No model is called and the development database is never touched.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Business, Escalation, KBChange, OnboardingSession, make_engine, make_session_factory
from app.main import create_app
from brain.brain import render_blocks
from app.services import onboarding
from app.services.onboarding import slugify
from brain.llm import ScriptedClient

ROOT = Path(__file__).resolve().parent.parent
PASTE = "Trousers shorten - 25 AED\nOpen Saturday to Thursday 10am - 10pm."
QUICK_HEADING = "# Quick mode"

KB = """---
business: Noor Tailoring
location: Shop 14, Karama, Dubai
currency: AED
default_language: en
fallback_reply: One moment, let me check with Noor. / لحظة، سأتأكد من نور.
last_reviewed: 2026-10-31
---

# Noor Tailoring: Knowledge Base

---

## Prices

### alterations-prices
**Visibility:** public · **Status:** confirmed

| Service | Price (AED) |
|---|---|
| Trousers shorten | 25 |

---

## Rules

### wedding-dresses
**Visibility:** internal · **Status:** confirmed

Wedding dresses: use `handoff`; only by appointment with the owner.
"""


def turn(message="What are your opening hours?", covered=("basics",), done=False) -> str:
    return json.dumps({"message": message, "covered": list(covered), "done": done})


def drafted(kb=KB, questions=("What is the WhatsApp number?",)) -> str:
    return json.dumps({"kb_markdown": kb, "open_questions": list(questions)})


def starters(*questions) -> str:
    return json.dumps({"questions": list(questions or (
        "How much to shorten trousers?", "Are you open on Friday?", "Do you make kanduras?", "How long do alterations take?"))})


def decision(**overrides) -> str:
    fields = {"reasoning": "Not in the KB.", "action": "ask_owner", "reply": "Let me check with Noor.",
              "cited_entries": [], "question_for_owner": "Do we do embroidery?"}
    if "handoff_reason" not in overrides:
        overrides["handoff_reason"] = "other" if overrides.get("action") == "handoff" else None
    return json.dumps({**fields, **overrides})


@pytest.fixture
def make():
    """Returns (TestClient, interview/chat ScriptedClient, draft ScriptedClient, session factory)."""
    def _make(responses=(), drafts=()):
        engine = make_engine("sqlite://")
        scripted = ScriptedClient(list(responses))
        draft_client = ScriptedClient(list(drafts))
        app = create_app(engine, scripted, draft_client=draft_client)
        return TestClient(app), scripted, draft_client, make_session_factory(engine)
    return _make


def start(client, mode="quick", name="Noor Tailoring", pasted=PASTE):
    response = client.post("/api/onboarding", json={"business_name": name, "mode": mode, "pasted_text": pasted})
    assert response.status_code == 200, response.text
    return response.json()


# --- Prompt blocks --------------------------------------------------------------------------------


def test_render_blocks_keeps_or_drops_each_block():
    text = "a\n<!-- if quick -->\nquick only\n<!-- end -->\nb\n<!-- if extra -->\nextra\n<!-- end -->\nc\n"
    assert render_blocks(text, {"quick": True, "extra": False}) == "a\nquick only\nb\nc\n"
    assert render_blocks(text, {"quick": False, "extra": True}) == "a\nb\nextra\nc\n"
    assert render_blocks("no blocks here\n", {}) == "no blocks here\n"
    with pytest.raises(KeyError):
        render_blocks(text, {"quick": True})


def test_interview_prompt_has_the_quick_block_only_in_quick_mode():
    quick = onboarding.interview_prompt("quick")
    full = onboarding.interview_prompt("full")
    assert QUICK_HEADING in quick and QUICK_HEADING not in full
    for rendered in (quick, full):
        assert "<!--" not in rendered
        assert "# Topics to cover" in rendered


# --- The interview --------------------------------------------------------------------------------


def test_quick_start_sends_the_paste_with_the_quick_prompt(make):
    client, scripted, _, sessions = make([turn("Thanks! May the assistant quote these prices?")])
    data = start(client)
    assert data["interviewer_message"] == "Thanks! May the assistant quote these prices?"
    assert data["covered"] == ["basics"] and data["done"] is False
    assert data["topics"] == ["basics", "hours", "services", "prices", "escalation", "style"]

    system, messages, schema = scripted.calls[0]
    assert QUICK_HEADING in system and "<!--" not in system
    assert schema["title"] == "InterviewTurn"
    assert messages[0]["role"] == "user"
    assert "Noor Tailoring" in messages[0]["content"]
    assert "Here is our info:" in messages[0]["content"] and PASTE in messages[0]["content"]

    with sessions() as session:
        row = session.scalar(select(OnboardingSession))
        assert str(row.id) == data["session_id"]
        assert row.mode == "quick" and row.business_name == "Noor Tailoring"
        assert [t["role"] for t in row.transcript] == ["owner", "interviewer"]
        assert row.business_id is None


def test_full_start_has_no_quick_block_and_names_the_business(make):
    client, scripted, _, _ = make([turn("Tell me about your business.", covered=())])
    data = start(client, mode="full", pasted=None)
    assert len(data["topics"]) == 14
    system, messages, _ = scripted.calls[0]
    assert QUICK_HEADING not in system
    assert "Noor Tailoring" in messages[0]["content"] and "Here is our info" not in messages[0]["content"]


def test_replies_grow_coverage_and_quick_mode_ends_when_the_model_says_done(make):
    client, scripted, _, sessions = make([
        turn(covered=("basics",)),
        turn("Who handles complaints?", covered=("hours",)),  # the model forgot basics: it stays covered
        turn("Here's the summary. Right?", covered=("basics", "hours", "prices")),
        turn("Great, all done.", covered=("basics", "hours", "prices"), done=True),  # services etc. uncovered
    ])
    sid = start(client)["session_id"]
    first = client.post(f"/api/onboarding/{sid}/reply", json={"text": "10am to 10pm"}).json()
    assert first["covered"] == ["basics", "hours"] and first["done"] is False
    client.post(f"/api/onboarding/{sid}/reply", json={"text": "Me, Noor."})
    last = client.post(f"/api/onboarding/{sid}/reply", json={"text": "Yes, that's right."}).json()
    assert last == {"interviewer_message": "Great, all done.", "covered": ["basics", "hours", "prices"], "done": True}

    # The model saw the whole conversation each time, with the quick prompt.
    system, messages, _ = scripted.calls[-1]
    assert QUICK_HEADING in system
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant", "user", "assistant", "user"]
    assert messages[-1]["content"] == "Yes, that's right."

    # Done: no more replies.
    refused = client.post(f"/api/onboarding/{sid}/reply", json={"text": "one more thing"})
    assert refused.status_code == 409
    with sessions() as session:
        row = session.scalar(select(OnboardingSession))
        assert row.done is True and len(row.transcript) == 8


def test_an_invalid_interviewer_turn_twice_is_a_clear_error_and_the_session_survives(make):
    client, _, _, sessions = make([turn(), "not json", "still not json", turn("Next question?")])
    sid = start(client)["session_id"]
    failed = client.post(f"/api/onboarding/{sid}/reply", json={"text": "hello"})
    assert failed.status_code == 503 and "try again" in failed.json()["detail"]
    with sessions() as session:
        assert len(session.scalar(select(OnboardingSession)).transcript) == 2  # nothing half-saved
    retried = client.post(f"/api/onboarding/{sid}/reply", json={"text": "hello"})
    assert retried.status_code == 200 and retried.json()["interviewer_message"] == "Next question?"


def test_unknown_sessions_and_bad_input(make):
    client, _, _, _ = make()
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/onboarding/{missing}/reply", json={"text": "hi"}).status_code == 404
    assert client.post(f"/api/onboarding/{missing}/draft").status_code == 404
    assert client.post(f"/api/onboarding/{missing}/publish", json={"kb_markdown": KB}).status_code == 404
    assert client.get(f"/api/onboarding/{missing}").status_code == 404
    assert client.post("/api/onboarding", json={"business_name": "", "mode": "quick"}).status_code == 422
    assert client.post("/api/onboarding", json={"business_name": "X", "mode": "other"}).status_code == 422
    too_long = "x" * 20001
    assert client.post("/api/onboarding", json={"business_name": "X", "mode": "quick",
                                                "pasted_text": too_long}).status_code == 422


# --- Draft and publish ----------------------------------------------------------------------------


def test_draft_is_saved_with_its_open_questions(make):
    client, _, draft_client, sessions = make([turn()], [drafted()])
    sid = start(client)["session_id"]
    data = client.post(f"/api/onboarding/{sid}/draft").json()
    assert data["kb_markdown"] == KB
    assert data["open_questions"] == ["What is the WhatsApp number?"]
    assert data["errors"] == []
    assert [s["title"] for s in data["sections"]] == ["Prices", "Rules"]
    assert data["sections"][1]["entries"][0]["visibility"] == "internal"

    system, messages, schema = draft_client.calls[0]
    assert schema["title"] == "KBDraft"
    assert "<interview_transcript>" in messages[0]["content"] and PASTE in messages[0]["content"]
    with sessions() as session:
        row = session.scalar(select(OnboardingSession))
        assert row.draft_kb == KB and row.open_questions == ["What is the WhatsApp number?"]

    # A reload picks up at the draft.
    state = client.get(f"/api/onboarding/{sid}").json()
    assert state["draft"]["kb_markdown"] == KB and state["published"] is None


def test_a_draft_that_fails_its_checks_twice_is_an_error(make):
    no_public = KB.replace("**Visibility:** public", "**Visibility:** internal")
    client, _, _, sessions = make([turn()], [drafted(no_public), drafted(no_public)])
    sid = start(client)["session_id"]
    failed = client.post(f"/api/onboarding/{sid}/draft")
    assert failed.status_code == 503
    with sessions() as session:
        assert session.scalar(select(OnboardingSession)).draft_kb is None


def test_check_reports_errors_in_plain_words(make):
    client, _, _, _ = make([turn()])
    sid = start(client)["session_id"]
    ok = client.post(f"/api/onboarding/{sid}/check", json={"kb_markdown": KB}).json()
    assert ok["errors"] == [] and len(ok["sections"]) == 2
    broken = client.post(f"/api/onboarding/{sid}/check", json={"kb_markdown": "# just a title\n"}).json()
    assert broken["errors"] and broken["sections"] == []
    no_fallback = KB.replace("fallback_reply:", "fallback:")
    assert "front matter is missing 'fallback_reply'" in client.post(
        f"/api/onboarding/{sid}/check", json={"kb_markdown": no_fallback}).json()["errors"]


def test_publish_rejects_an_invalid_kb(make):
    client, _, _, sessions = make([turn()])
    sid = start(client)["session_id"]
    refused = client.post(f"/api/onboarding/{sid}/publish", json={"kb_markdown": "nothing here"})
    assert refused.status_code == 422 and "no entries" in refused.json()["detail"]
    with sessions() as session:
        assert session.scalar(select(Business).where(Business.slug != "the-plug")) is None


def test_publish_creates_the_business_and_a_repeat_returns_the_same_links(make):
    client, scripted, _, sessions = make([turn(), starters()])
    sid = start(client)["session_id"]
    links = client.post(f"/api/onboarding/{sid}/publish", json={"kb_markdown": KB}).json()
    assert links["slug"] == "noor-tailoring"
    assert links["chat_url"].endswith("/b/noor-tailoring")
    assert "/owner/noor-tailoring?key=" in links["owner_url"]
    assert links["chat_url"] in links["embed_html"] and links["embed_html"].startswith("<iframe")

    # The starter questions came from the public entries only.
    system, messages, schema = scripted.calls[-1]
    assert schema["title"] == "StarterQuestions"
    assert "Trousers shorten" in messages[0]["content"] and "Wedding dresses" not in messages[0]["content"]

    with sessions() as session:
        business = session.scalar(select(Business).where(Business.slug == "noor-tailoring"))
        assert business.name == "Noor Tailoring" and business.kb_version == 1
        assert business.kb_markdown == onboarding.with_default_languages(KB)  # plus languages: en, el, ar
        assert len(business.owner_key) == 24 and links["owner_url"].endswith(business.owner_key)
        assert business.suggestions[0] == "How much to shorten trousers?" and len(business.suggestions) == 4
        changes = session.scalars(select(KBChange).where(KBChange.business_id == business.id)).all()
        assert [(c.change, c.new_text) for c in changes] == [("initial", onboarding.with_default_languages(KB))]
        assert session.scalar(select(OnboardingSession)).business_id == business.id

    # Publishing again (a double click, a reload) returns the same business and calls no model.
    calls = len(scripted.calls)
    again = client.post(f"/api/onboarding/{sid}/publish", json={"kb_markdown": KB}).json()
    assert again == links and len(scripted.calls) == calls
    with sessions() as session:
        assert len(session.scalars(select(Business)).all()) == 2
    assert client.post(f"/api/onboarding/{sid}/reply", json={"text": "hi"}).status_code == 409
    assert client.post(f"/api/onboarding/{sid}/draft").status_code == 409
    assert client.get(f"/api/onboarding/{sid}").json()["published"] == links


def test_slugs_are_unique_and_starter_questions_fall_back_to_none(make):
    client, _, _, sessions = make([turn(), starters(), turn(), "not json"])
    first = start(client)["session_id"]
    second = start(client)["session_id"]
    assert client.post(f"/api/onboarding/{first}/publish", json={"kb_markdown": KB}).json()["slug"] == "noor-tailoring"
    links = client.post(f"/api/onboarding/{second}/publish", json={"kb_markdown": KB}).json()
    assert links["slug"] == "noor-tailoring-2"
    with sessions() as session:
        assert session.scalar(select(Business).where(Business.slug == "noor-tailoring-2")).suggestions == []
    public = client.get("/api/b/noor-tailoring-2/public").json()
    assert {k: public[k] for k in ("name", "suggestions", "languages", "ui_languages", "accent", "email_capture")} == {
        "name": "Noor Tailoring", "suggestions": [], "languages": ["en", "el", "ar"],
        "ui_languages": ["en", "el", "ar"], "accent": None, "email_capture": False}


def test_the_slug_follows_the_typed_name(make):
    client, _, _, sessions = make([turn(), starters(), turn(), starters()])
    typed = start(client, name="Noor")["session_id"]
    assert client.post(f"/api/onboarding/{typed}/publish", json={"kb_markdown": KB}).json()["slug"] == "noor"
    arabic = start(client, name="خياطة نور")["session_id"]  # no Latin letters: the KB's name instead
    assert client.post(f"/api/onboarding/{arabic}/publish", json={"kb_markdown": KB}).json()["slug"] == "noor-tailoring"
    with sessions() as session:
        assert session.scalar(select(Business).where(Business.slug == "noor")).name == "Noor Tailoring"


def test_slugify():
    assert slugify("Noor Tailoring & Alterations") == "noor-tailoring-alterations"
    assert slugify("  Café Été  ") == "cafe-ete"
    assert slugify("خياطة نور") == "business"
    assert len(slugify("x" * 200)) <= 40


def test_the_new_business_chats_and_escalates_into_its_own_inbox(make):
    learn = json.dumps({
        "reasoning": "Applies to every customer.", "reply_to_customer": "Sorry, we don't do embroidery.",
        "learn_action": "add", "target_entry_id": None,
        "proposed_entry": {"id": "no-embroidery", "visibility": "public", "text": "We don't do embroidery."},
        "owner_summary": "Save: no embroidery.",
    })
    client, _, _, sessions = make([turn(), starters(), decision(), learn])
    sid = start(client)["session_id"]
    links = client.post(f"/api/onboarding/{sid}/publish", json={"kb_markdown": KB}).json()
    key = links["owner_url"].split("key=")[1]

    assert client.get("/b/noor-tailoring").status_code == 200
    chat = client.post("/api/b/noor-tailoring/chat", json={"message": "do you do embroidery?"}).json()
    assert chat["state"] == "waiting_on_owner" and chat["message"]["action"] == "ask_owner"

    inbox = client.get("/api/owner/noor-tailoring/escalations", headers={"X-Owner-Key": key}).json()["escalations"]
    assert [e["question"] for e in inbox] == ["Do we do embroidery?"]
    knowledge = client.get("/api/owner/noor-tailoring/knowledge", headers={"X-Owner-Key": key}).json()
    assert knowledge["name"] == "Noor Tailoring" and knowledge["can_reset_demo"] is False
    stats = client.get("/api/owner/noor-tailoring/stats", headers={"X-Owner-Key": key}).json()
    assert stats["messages_this_week"] == 1 and stats["pending"] == 1 and stats["answered_by_bot_pct"] == 0

    # Learning works too: the answer goes to the customer and Save adds the entry to Noor's KB.
    headers = {"X-Owner-Key": key}
    answered = client.post(f"/api/owner/noor-tailoring/escalations/{inbox[0]['id']}/answer",
                           json={"text": "No, we don't do embroidery."}, headers=headers)
    assert answered.status_code == 200
    saved = client.post(f"/api/owner/noor-tailoring/escalations/{inbox[0]['id']}/learn",
                        json={"decision": "saved"}, headers=headers).json()
    assert saved == {"ok": True, "entry_id": "no-embroidery"}
    learned = client.get("/api/owner/noor-tailoring/knowledge", headers=headers).json()["learned"]
    assert [e["id"] for e in learned] == ["no-embroidery"]

    # Not The Plug's: its inbox stays empty, and Noor's key doesn't open it.
    with sessions() as session:
        plug = session.scalar(select(Business).where(Business.slug == "the-plug"))
        noor = session.scalar(select(Business).where(Business.slug == "noor-tailoring"))
        assert session.scalar(select(Escalation).where(Escalation.business_id == plug.id)) is None
        assert session.scalar(select(Escalation).where(Escalation.business_id == noor.id)) is not None
    assert client.get("/api/owner/the-plug/escalations", headers={"X-Owner-Key": key}).status_code == 403
    assert client.post("/api/owner/noor-tailoring/reset-demo", headers={"X-Owner-Key": key}).status_code == 404


def test_start_page_is_served(make):
    client, _, _, _ = make()
    page = client.get("/start")
    assert page.status_code == 200 and "/static/start.js" in page.text


def test_published_kbs_get_jawabs_languages_unless_they_say():
    from app.services.onboarding import with_default_languages
    from brain.kb import parse_kb

    plain = "---\nbusiness: Test\ncurrency: EUR\n---\n\n### hello\n**Visibility:** public · **Status:** confirmed\n\nHi.\n"
    assert parse_kb(with_default_languages(plain)).languages == ["en", "el", "ar"]
    greek = plain.replace("currency: EUR", "languages: en, el")
    assert with_default_languages(greek) == greek
    assert with_default_languages("no front matter\n") == "no front matter\n"
