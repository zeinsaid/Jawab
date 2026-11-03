"""Learning (spec section 7, "Applying a saved entry"): Save / Edit / Just this once on an answered
question, on an in-memory SQLite database with a ScriptedClient. No model is called.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Business, Escalation, KBChange, make_engine, make_session_factory
from app.main import create_app
from app.services import kb_edit
from brain.kb import parse_kb
from brain.llm import ScriptedClient

CHAT = "/api/b/the-plug/chat"
OWNER = "/api/owner/the-plug"
CUSTOMER_QUESTION = "هل أنتم مفتوحون يوم عيد الميلاد؟"
CHRISTMAS_TEXT = "Closed on 25 December. Open 24/7 again from 26 December."


def ask(question="Are we open on Christmas Day (25 December)?") -> str:
    return json.dumps({
        "reasoning": "The KB doesn't cover this.",
        "action": "ask_owner",
        "reply": "دعني أتحقق من الفريق وأعود إليك.",
        "cited_entries": [],
        "question_for_owner": question,
    })


def answer(cited) -> str:
    return json.dumps({
        "reasoning": "A learned entry covers it.",
        "action": "answer",
        "reply": "We're closed on 25 December and open 24/7 again from the 26th.",
        "cited_entries": cited,
        "question_for_owner": None,
    })


def learn(**overrides) -> str:
    fields = {
        "reasoning": "Christmas closing applies to every customer, so it's worth saving.",
        "reply_to_customer": "نحن مغلقون يوم ٢٥ ديسمبر.",
        "learn_action": "add",
        "target_entry_id": None,
        "proposed_entry": {"id": "holiday-christmas", "visibility": "public", "text": CHRISTMAS_TEXT},
        "owner_summary": "Save: closed on 25 December, back to 24/7 on the 26th.",
    }
    return json.dumps({**fields, **overrides})


NONE = dict(learn_action="none", proposed_entry=None, owner_summary="Nothing to save: a one-off answer.")


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


def answered_question(client, headers, message=CUSTOMER_QUESTION) -> int:
    """A new chat whose question the owner has answered (uses one ask + one learn response)."""
    client.post(CHAT, json={"message": message})
    escalations = client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"]
    escalation_id = next(e["id"] for e in escalations if e["kind"] == "ask_owner" and e["status"] == "pending")
    response = client.post(f"{OWNER}/escalations/{escalation_id}/answer", json={"text": "Closed on the 25th."},
                           headers=headers)
    assert response.status_code == 200
    return escalation_id


def business_row(sessions):
    with sessions() as session:
        business = session.scalar(select(Business))
        session.expunge(business)
        return business


def decide(client, headers, escalation_id, decision, entry=None):
    body = {"decision": decision} if entry is None else {"decision": decision, "entry": entry}
    return client.post(f"{OWNER}/escalations/{escalation_id}/learn", json=body, headers=headers)


def test_saving_an_add_proposal_teaches_the_bot(make):
    client, scripted, sessions, headers = make(ask(), learn(), answer(["holiday-christmas"]))
    before = business_row(sessions)
    escalation_id = answered_question(client, headers)

    response = decide(client, headers, escalation_id, "saved")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "entry_id": "holiday-christmas"}

    business = business_row(sessions)
    assert business.kb_version == before.kb_version + 1
    kb = parse_kb(business.kb_markdown)  # the saved KB is valid
    entry = kb.entries["holiday-christmas"]
    assert (str(entry.visibility), entry.status, entry.text) == ("public", "learned", CHRISTMAS_TEXT)
    assert len(kb.entries) == len(parse_kb(before.kb_markdown).entries) + 1
    assert business.kb_markdown.startswith(before.kb_markdown.rstrip("\n"))
    assert business.kb_markdown.endswith(
        "\n---\n\n## Learned from the owner\n\n### holiday-christmas\n"
        "**Visibility:** public · **Status:** learned\n\n" + CHRISTMAS_TEXT + "\n")

    with sessions() as session:
        change = session.scalar(select(KBChange).where(KBChange.source_escalation_id == escalation_id))
        assert (change.entry_id, change.change, change.old_text, change.new_text) == (
            "holiday-christmas", "add", None, CHRISTMAS_TEXT)
        assert session.get(Escalation, escalation_id).learn_decision == "saved"

    # The card shows the decision, and the stats count it.
    card = next(e for e in client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"]
                if e["id"] == escalation_id)
    assert (card["learn_decision"], card["learned_entry_id"]) == ("saved", "holiday-christmas")
    assert client.get(f"{OWNER}/stats", headers=headers).json()["questions_learned"] == 1

    # Knowledge tab: learned entries first, with the customer question they came from, listed once.
    knowledge = client.get(f"{OWNER}/knowledge", headers=headers).json()
    assert [e["id"] for e in knowledge["learned"]] == ["holiday-christmas"]
    assert knowledge["learned"][0]["source_question"] == CUSTOMER_QUESTION
    assert knowledge["learned"][0]["learned_at"]
    assert all(e["id"] != "holiday-christmas" for s in knowledge["sections"] for e in s["entries"])

    # The very next customer message gets a brain built from the new KB, and the panel marks it learned.
    chat = client.post(CHAT, json={"message": "are you open on christmas day?"}).json()
    system, messages, _ = scripted.calls[-1]
    assert "### holiday-christmas" in system + json.dumps(messages)
    assert chat["panel"]["sources"] == [{"id": "holiday-christmas", "text": CHRISTMAS_TEXT, "learned": True}]


def test_just_this_once_changes_nothing(make):
    client, _, sessions, headers = make(ask(), learn(**NONE))
    before = business_row(sessions)
    escalation_id = answered_question(client, headers)

    response = decide(client, headers, escalation_id, "once")
    assert response.json() == {"ok": True}
    after = business_row(sessions)
    assert (after.kb_version, after.kb_markdown) == (before.kb_version, before.kb_markdown)
    with sessions() as session:
        assert session.get(Escalation, escalation_id).learn_decision == "once"
        assert session.scalar(select(KBChange).where(KBChange.source_escalation_id.is_not(None))) is None
    assert client.get(f"{OWNER}/stats", headers=headers).json()["questions_learned"] == 0


def test_saving_an_update_replaces_the_body_and_marks_it_learned(make):
    new_text = "We're open 24 hours a day, 7 days a week, except 25 December."
    client, _, sessions, headers = make(ask(), learn(
        learn_action="update", target_entry_id="shop-hours",
        proposed_entry={"id": "shop-hours", "visibility": "public", "text": new_text}))
    before = business_row(sessions)
    old = parse_kb(before.kb_markdown).entries["shop-hours"]
    escalation_id = answered_question(client, headers)

    assert decide(client, headers, escalation_id, "saved").json() == {"ok": True, "entry_id": "shop-hours"}
    after = business_row(sessions)
    kb, kb_before = parse_kb(after.kb_markdown), parse_kb(before.kb_markdown)
    assert (kb.entries["shop-hours"].text, kb.entries["shop-hours"].status) == (new_text, "learned")
    assert after.kb_version == before.kb_version + 1
    # Everything else is untouched, and no learned section was added.
    assert list(kb.entries) == list(kb_before.entries)
    assert all(kb.entries[i] == kb_before.entries[i] for i in kb.entries if i != "shop-hours")
    assert "## Learned from the owner" not in after.kb_markdown
    with sessions() as session:
        change = session.scalar(select(KBChange).where(KBChange.source_escalation_id == escalation_id))
        assert (change.change, change.old_text, change.new_text) == ("update", old.text, new_text)

    knowledge = client.get(f"{OWNER}/knowledge", headers=headers).json()
    assert [e["id"] for e in knowledge["learned"]] == ["shop-hours"]
    assert all(e["id"] != "shop-hours" for s in knowledge["sections"] for e in s["entries"])


def test_edited_entries_and_id_clashes(make):
    client, _, sessions, headers = make(ask(), learn(), ask("Do we print A5?"), learn(**NONE))
    first = answered_question(client, headers)
    edited = {"id": "holiday-christmas", "visibility": "internal", "text": "Closed 25 Dec.\n- Back on the 26th."}
    assert decide(client, headers, first, "edited", edited).json() == {"ok": True, "entry_id": "holiday-christmas"}

    # "Save anyway" on a one-off answer: an edited entry with a taken ID gets -2, in the same section.
    second = answered_question(client, headers, "do you print A5?")
    response = decide(client, headers, second, "edited",
                      {"id": "holiday-christmas", "visibility": "public", "text": "A5 costs the same as A4."})
    assert response.json() == {"ok": True, "entry_id": "holiday-christmas-2"}

    business = business_row(sessions)
    kb = parse_kb(business.kb_markdown)
    assert str(kb.entries["holiday-christmas"].visibility) == "internal"
    assert kb.entries["holiday-christmas"].text == "Closed 25 Dec.\n- Back on the 26th."
    assert kb.entries["holiday-christmas-2"].status == "learned"
    assert business.kb_markdown.count("## Learned from the owner") == 1
    assert list(kb.entries)[-2:] == ["holiday-christmas", "holiday-christmas-2"]
    with sessions() as session:
        assert session.get(Escalation, first).learn_decision == "edited"
    assert client.get(f"{OWNER}/stats", headers=headers).json()["questions_learned"] == 2


def test_an_edit_that_keeps_an_update_target_updates_it_otherwise_adds(make):
    client, _, sessions, headers = make(ask(), learn(
        learn_action="update", target_entry_id="shop-hours",
        proposed_entry={"id": "shop-hours", "visibility": "public", "text": "Open 24/7."}))
    escalation_id = answered_question(client, headers)
    response = decide(client, headers, escalation_id, "edited",
                      {"id": "holiday-hours", "visibility": "public", "text": "Closed on 25 December."})
    assert response.json() == {"ok": True, "entry_id": "holiday-hours"}
    kb = parse_kb(business_row(sessions).kb_markdown)
    assert kb.entries["shop-hours"].status == "confirmed"  # the proposed target is left alone
    assert kb.entries["holiday-hours"].status == "learned"


def test_an_invalid_entry_saves_nothing(make):
    client, _, sessions, headers = make(ask(), learn())
    before = business_row(sessions)
    escalation_id = answered_question(client, headers)

    for bad in ({"id": "holiday-christmas", "visibility": "public", "text": "Closed.\n# Not a heading"},
                {"id": "holiday-christmas", "visibility": "public", "text": "Closed.\n---\nmore"},
                {"id": "Holiday Christmas", "visibility": "public", "text": "Closed."}):
        response = decide(client, headers, escalation_id, "edited", bad)
        assert response.status_code == 200
        assert response.json()["ok"] is False and response.json()["error"]
    after = business_row(sessions)
    assert (after.kb_version, after.kb_markdown) == (before.kb_version, before.kb_markdown)
    with sessions() as session:
        assert session.get(Escalation, escalation_id).learn_decision is None

    # Still undecided, so a valid save goes through.
    assert decide(client, headers, escalation_id, "saved").json()["ok"] is True


def test_a_second_decision_is_refused(make):
    client, _, sessions, headers = make(ask(), learn())
    escalation_id = answered_question(client, headers)
    assert decide(client, headers, escalation_id, "saved").json()["ok"] is True
    version = business_row(sessions).kb_version

    for decision in ("saved", "once"):
        response = decide(client, headers, escalation_id, decision)
        assert response.status_code == 409
        assert "already" in response.json()["detail"]
    assert business_row(sessions).kb_version == version


def test_learn_route_checks(make):
    client, _, _, headers = make(ask(), learn(), ask(), "not json", "still not json")
    escalation_id = answered_question(client, headers)

    assert decide(client, {"X-Owner-Key": "wrong"}, escalation_id, "saved").status_code == 403
    assert decide(client, headers, 9999, "saved").status_code == 404
    assert decide(client, headers, escalation_id, "maybe").status_code == 422
    assert decide(client, headers, escalation_id, "edited").status_code == 422

    # A question still waiting for the owner can't be saved yet.
    client.post(CHAT, json={"message": "and on new year's day?"})
    pending = next(e for e in client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"]
                   if e["status"] == "pending")
    assert decide(client, headers, pending["id"], "saved").status_code == 409

    # The learn call failed twice (fallback): nothing to Save, but an edit can still be saved.
    client.post(f"{OWNER}/escalations/{pending['id']}/answer", json={"text": "Closed."}, headers=headers)
    assert decide(client, headers, pending["id"], "saved").json()["ok"] is False
    entry = {"id": "holiday-new-year", "visibility": "public", "text": "Closed on 1 January."}
    assert decide(client, headers, pending["id"], "edited", entry).json() == {"ok": True, "entry_id": "holiday-new-year"}


def test_kb_edit_handles_section_and_end_of_file_cases():
    kb = ("### a\n**Visibility:** public · **Status:** confirmed\n\nA text.\n\n---\n\n"
          "## Learned from the owner\n\n### b\n**Visibility:** public · **Status:** learned\n\nB text.\n\n"
          "---\n\n## Later\n\n### c\n**Visibility:** internal · **Status:** confirmed\n\nC text.")
    added = kb_edit.add_entry(kb, "d", "public", "D text.")
    parsed = parse_kb(added)
    assert list(parsed.entries) == ["a", "b", "d", "c"]  # inside the learned section, before the next one
    assert parsed.entries["d"].text == "D text." and parsed.entries["c"].text == "C text."

    updated, old = kb_edit.update_entry(kb, "c", "public", "New C.\n- point")
    parsed = parse_kb(updated)
    assert old == "C text."
    assert (str(parsed.entries["c"].visibility), parsed.entries["c"].status) == ("public", "learned")
    assert parsed.entries["c"].text == "New C.\n- point"
    assert kb_edit.free_id("b", parsed.entries) == "b-2"
    assert kb_edit.entry_problems("x-1", "public", "  # no") and not kb_edit.entry_problems("x-1", "internal", "ok")


def test_reset_demo_restores_the_kb_and_clears_the_chats(make):
    client, scripted, sessions, headers = make(ask(), learn(), answer(["holiday-christmas"]), ask())
    seed = business_row(sessions)
    escalation_id = answered_question(client, headers)
    decide(client, headers, escalation_id, "saved")
    client.post(CHAT, json={"message": "are you open on christmas day?"})
    client.post(CHAT, json={"message": "and on new year's day?"})
    assert client.get(f"{OWNER}/knowledge", headers=headers).json()["can_reset_demo"] is True

    assert client.post(f"{OWNER}/reset-demo", headers={"X-Owner-Key": "wrong"}).status_code == 403
    response = client.post(f"{OWNER}/reset-demo", headers=headers)
    assert response.status_code == 200
    after = business_row(sessions)
    assert response.json() == {"ok": True, "kb_version": after.kb_version}
    assert after.kb_markdown == seed.kb_markdown
    assert after.kb_version == seed.kb_version + 2  # +1 for the save, +1 for the reset

    from app.db import Conversation, Message
    with sessions() as session:
        for model in (Conversation, Message, Escalation):
            assert session.scalar(select(model)) is None, model.__name__
        # Only the seed's "initial" change is left: the learned ones went with their escalations.
        assert session.scalars(select(KBChange.change)).all() == ["initial"]
    assert client.get(f"{OWNER}/escalations", headers=headers).json()["escalations"] == []
    assert client.get(f"{OWNER}/stats", headers=headers).json()["questions_learned"] == 0
    assert client.get(f"{OWNER}/knowledge", headers=headers).json()["learned"] == []

    # The next customer message gets a brain built from the original KB again.
    client.post(CHAT, json={"message": "are you open on christmas day?"})
    system, messages, _ = scripted.calls[-1]
    assert "### holiday-christmas" not in system + json.dumps(messages)


def test_only_the_demo_business_can_be_reset(make):
    from app.services import owner
    client, _, sessions, headers = make()
    with sessions() as session:
        other = Business(slug="noor", name="Noor", owner_key="k" * 24, kb_markdown=business_row(sessions).kb_markdown,
                         kb_version=1, suggestions=[])
        session.add(other)
        session.commit()
        assert owner.demo_seed(other) is None
        with pytest.raises(owner.NotFound):
            owner.reset_demo(session, other)
    response = client.post("/api/owner/noor/reset-demo", headers={"X-Owner-Key": "k" * 24})
    assert response.status_code == 404
    assert client.get("/api/owner/noor/knowledge", headers={"X-Owner-Key": "k" * 24}).json()["can_reset_demo"] is False
