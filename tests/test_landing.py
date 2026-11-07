"""The landing page and its public stats (spec section 9), plus what every page's <head> shares.

In-memory SQLite and a ScriptedClient: no model is called and the development database is never touched.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.db import Business, make_engine, make_session_factory
from app.main import create_app
from brain.llm import ScriptedClient


def decision(action="answer", cited=("shop-hours",)) -> str:
    return json.dumps({"reasoning": "SECRET", "action": action,
                       "handoff_reason": "other" if action == "handoff" else None, "reply": "We're open 24/7.",
                       "cited_entries": list(cited),
                       "question_for_owner": "Christmas hours?" if action == "ask_owner" else None})


@pytest.fixture
def make():
    def _make(*responses):
        engine = make_engine("sqlite://")
        return TestClient(create_app(engine, ScriptedClient(list(responses)))), make_session_factory(engine)
    return _make


def test_public_stats_return_only_the_three_numbers(make):
    client, _ = make(decision(), decision("ask_owner", cited=()))
    empty = client.get("/api/public-stats/the-plug").json()
    assert empty == {"messages_handled": 0, "answered_without_owner_pct": None, "questions_learned": 0}

    client.post("/api/b/the-plug/chat", json={"message": "Are you open now?"})
    client.post("/api/b/the-plug/chat", json={"message": "Open on Christmas?"})
    stats = client.get("/api/public-stats/the-plug").json()
    assert stats == {"messages_handled": 2, "answered_without_owner_pct": 50, "questions_learned": 0}


def test_public_stats_are_only_for_the_demo_business(make):
    client, sessions = make()
    assert client.get("/api/public-stats/nobody").status_code == 404
    with sessions() as session:  # any business that isn't the demo
        session.execute(update(Business).where(Business.slug == "the-plug").values(slug="other-shop"))
        session.commit()
    assert client.get("/api/public-stats/other-shop").status_code == 404


def test_landing_page_has_both_buttons_and_a_link_preview(make):
    client, _ = make()
    page = client.get("/")
    assert page.status_code == 200
    for needed in ('href="/try"', 'href="/start"', '<meta property="og:title"',
                   '<meta property="og:description"', '<meta name="description"', "/static/landing.js",
                   "/static/favicon.svg", 'class="wordmark" href="/"'):
        assert needed in page.text


def test_chat_page_preview_names_the_business_safely(make):
    client, sessions = make()
    with sessions() as session:
        session.execute(update(Business).values(name='Tom & "Jerry" <b>'))
        session.commit()
    page = client.get("/b/the-plug").text
    assert "{{business_name}}" not in page
    assert '<meta property="og:title" content="Tom &amp; &quot;Jerry&quot; &lt;b&gt; · Ask us anything">' in page
    assert "<b>" not in page


def test_every_page_has_the_wordmark_and_favicon(make):
    client, _ = make()
    for path in ("/", "/b/the-plug", "/owner/the-plug", "/start", "/try"):
        page = client.get(path).text
        assert 'class="wordmark" href="/"' in page and "جواب" in page, path
        assert '<link rel="icon" href="/static/favicon.svg"' in page, path
        assert '<meta name="description"' in page, path
    favicon = client.get("/static/favicon.svg")
    assert favicon.status_code == 200 and "#0F766E" in favicon.text
