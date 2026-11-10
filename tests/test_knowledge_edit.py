"""Direct edits from the owner's Knowledge tab (D-015): edit an entry, add one, download the KB.

In-memory SQLite and a ScriptedClient, like test_owner_api.py: no model is called.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Business, KBChange, make_engine, make_session_factory
from app.main import create_app
from brain.llm import ScriptedClient

CHAT = "/api/b/the-plug/chat"
OWNER = "/api/owner/the-plug"
NEW_LOCATION = ("Address: Asomatou 9, Egkomi, Lefkosia 2414, Cyprus.\n\n"
                "Just off 28th October Avenue, right behind the Mall of Engomi.")


def answer_decision() -> str:
    return json.dumps({"reasoning": "Location question.", "action": "answer", "handoff_reason": None,
                       "reply": "We're behind the mall.", "cited_entries": ["shop-location"],
                       "question_for_owner": None})


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


def entry_in(kb: dict, entry_id: str) -> dict:
    return next(e for group in [kb["learned"], *[s["entries"] for s in kb["sections"]]]
                for e in group if e["id"] == entry_id)


def test_owner_edits_an_entry_and_the_bot_uses_it_on_the_next_message(make):
    client, scripted, sessions, headers = make(answer_decision())
    before = client.get(f"{OWNER}/knowledge", headers=headers).json()
    old = entry_in(before, "shop-location")

    r = client.put(f"{OWNER}/knowledge/shop-location", headers=headers,
                   json={"visibility": "public", "text": NEW_LOCATION, "base_text": old["text"]})
    assert r.status_code == 200 and r.json()["changed"] is True
    assert r.json()["kb_version"] == before["kb_version"] + 1

    after = client.get(f"{OWNER}/knowledge", headers=headers).json()
    edited = entry_in(after, "shop-location")
    assert edited["text"] == NEW_LOCATION
    assert edited["status"] == "confirmed" and edited["edited_at"]  # stays put, keeps its status
    assert [s["title"] for s in after["sections"]] == [s["title"] for s in before["sections"]]
    assert after["entry_count"] == before["entry_count"]

    client.post(CHAT, json={"message": "where are you?"})
    system_prompt = scripted.calls[-1][0]
    assert "28th October Avenue" in system_prompt and "right behind the Mall of Engomi." in system_prompt

    with sessions() as session:
        change = session.scalar(select(KBChange).where(KBChange.change == "manual_edit"))
        assert change.entry_id == "shop-location" and change.new_text == NEW_LOCATION
        assert change.old_text == old["text"] and change.source_escalation_id is None


def test_editing_a_placeholder_confirms_it(make):
    client, _, sessions, headers = make()
    with sessions() as session:
        business = session.scalar(select(Business).where(Business.slug == "the-plug"))
        marked = business.kb_markdown.replace(
            "### shop-wifi\n**Visibility:** public · **Status:** confirmed",
            "### shop-wifi\n**Visibility:** public · **Status:** placeholder", 1)
        assert marked != business.kb_markdown
        business.kb_markdown = marked
        business.kb_version += 1
        session.commit()
    r = client.put(f"{OWNER}/knowledge/shop-wifi", headers=headers,
                   json={"visibility": "public", "text": "Free Wi-Fi in the shop; ask staff for the password."})
    assert r.status_code == 200
    assert entry_in(client.get(f"{OWNER}/knowledge", headers=headers).json(), "shop-wifi")["status"] == "confirmed"


def test_an_unchanged_save_changes_nothing(make):
    client, _, sessions, headers = make()
    kb = client.get(f"{OWNER}/knowledge", headers=headers).json()
    hours = entry_in(kb, "shop-hours")
    r = client.put(f"{OWNER}/knowledge/shop-hours", headers=headers,
                   json={"visibility": hours["visibility"], "text": hours["text"], "base_text": hours["text"]})
    assert r.status_code == 200 and r.json()["changed"] is False
    assert client.get(f"{OWNER}/knowledge", headers=headers).json()["kb_version"] == kb["kb_version"]
    with sessions() as session:
        assert session.scalar(select(KBChange).where(KBChange.change == "manual_edit")) is None


def test_a_stale_edit_is_refused(make):
    client, _, _, headers = make()
    old = entry_in(client.get(f"{OWNER}/knowledge", headers=headers).json(), "shop-location")
    first = client.put(f"{OWNER}/knowledge/shop-location", headers=headers,
                       json={"visibility": "public", "text": NEW_LOCATION, "base_text": old["text"]})
    assert first.status_code == 200
    # A second tab still holding the old text must not overwrite the first edit.
    second = client.put(f"{OWNER}/knowledge/shop-location", headers=headers,
                        json={"visibility": "public", "text": "Something else.", "base_text": old["text"]})
    assert second.status_code == 409 and "changed after you opened it" in second.json()["detail"]
    assert entry_in(client.get(f"{OWNER}/knowledge", headers=headers).json(), "shop-location")["text"] == NEW_LOCATION


def test_bad_edits_are_refused_with_a_reason(make):
    client, _, _, headers = make()
    unknown = client.put(f"{OWNER}/knowledge/no-such-entry", headers=headers,
                         json={"visibility": "public", "text": "Hello."})
    assert unknown.status_code == 404
    heading = client.put(f"{OWNER}/knowledge/shop-wifi", headers=headers,
                         json={"visibility": "public", "text": "Free Wi-Fi.\n### sneaky-new-entry"})
    assert heading.status_code == 422 and "#" in heading.json()["detail"]
    rule = client.put(f"{OWNER}/knowledge/shop-wifi", headers=headers,
                      json={"visibility": "public", "text": "Free Wi-Fi.\n---\nmore"})
    assert rule.status_code == 422
    blank = client.put(f"{OWNER}/knowledge/shop-wifi", headers=headers, json={"visibility": "public", "text": "  "})
    assert blank.status_code == 422


def test_knowledge_edits_need_the_owner_key(make):
    client, _, _, _ = make()
    body = {"visibility": "public", "text": "Hacked."}
    assert client.put(f"{OWNER}/knowledge/shop-wifi", json=body).status_code == 403
    assert client.put(f"{OWNER}/knowledge/shop-wifi", json=body, headers={"X-Owner-Key": "wrong"}).status_code == 403
    assert client.post(f"{OWNER}/knowledge", json={"id": "x-y", **body}).status_code == 403
    assert client.get(f"{OWNER}/knowledge/export").status_code == 403


def test_owner_adds_an_entry(make):
    client, _, sessions, headers = make()
    before = client.get(f"{OWNER}/knowledge", headers=headers).json()
    r = client.post(f"{OWNER}/knowledge", headers=headers,
                    json={"id": "holiday-christmas", "visibility": "public", "text": "Closed on 25 December."})
    assert r.status_code == 200 and r.json()["entry_id"] == "holiday-christmas"
    after = client.get(f"{OWNER}/knowledge", headers=headers).json()
    assert after["entry_count"] == before["entry_count"] + 1
    added = entry_in(after, "holiday-christmas")
    assert added["status"] == "learned" and added["learned_at"]  # listed with the learned entries
    taken = client.post(f"{OWNER}/knowledge", headers=headers,
                        json={"id": "holiday-christmas", "visibility": "public", "text": "Again."})
    assert taken.status_code == 409 and "already an entry" in taken.json()["detail"]
    bad_id = client.post(f"{OWNER}/knowledge", headers=headers,
                         json={"id": "Christmas Day", "visibility": "public", "text": "Closed."})
    assert bad_id.status_code == 422
    with sessions() as session:
        assert session.scalar(select(KBChange).where(KBChange.change == "manual_add")).entry_id == "holiday-christmas"


def test_export_downloads_the_live_kb(make):
    client, _, _, headers = make()
    client.put(f"{OWNER}/knowledge/shop-location", headers=headers, json={"visibility": "public", "text": NEW_LOCATION})
    r = client.get(f"{OWNER}/knowledge/export", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert 'filename="the-plug-kb-v' in r.headers["content-disposition"]
    assert "28th October Avenue" in r.text and r.text.startswith("---")


def test_reset_demo_forgets_manual_edits(make):
    """A reset demo goes back to the file's KB, so the 'Edited' labels must go too."""
    client, _, sessions, headers = make()
    with sessions() as session:
        demo = session.scalar(select(Business).where(Business.slug == "the-plug"))
        can_reset = client.get(f"{OWNER}/knowledge", headers=headers).json()["can_reset_demo"]
    if not can_reset:
        pytest.skip("The seeded business isn't a demo in this configuration.")
    client.put(f"{OWNER}/knowledge/shop-location", headers=headers, json={"visibility": "public", "text": NEW_LOCATION})
    assert client.post(f"{OWNER}/reset-demo", headers=headers).status_code == 200
    assert entry_in(client.get(f"{OWNER}/knowledge", headers=headers).json(), "shop-location")["edited_at"] is None
    with sessions() as session:
        assert session.scalar(select(KBChange).where(KBChange.change.in_(["manual_edit", "manual_add"]))) is None
