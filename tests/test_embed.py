"""The floating chat bubble: /embed.js, the Share tab snippet and the demo shop website.

In-memory SQLite and a ScriptedClient: no model is called and the development database is never touched.
"""

import pytest
from fastapi.testclient import TestClient

from app.db import make_engine
from app.main import create_app
from brain.llm import ScriptedClient


@pytest.fixture
def client():
    return TestClient(create_app(make_engine("sqlite://"), ScriptedClient([])))


def test_embed_script_is_filled_in_for_the_business(client):
    response = client.get("/embed.js?b=the-plug")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    script = response.text
    assert 'var SLUG = "the-plug";' in script
    assert 'var BASE = "http://testserver";' in script
    assert "__JAWAB_" not in script
    assert '"/b/" + encodeURIComponent(SLUG) + "?embed=1"' in script
    assert "#0F766E" in script
    assert script.lstrip().startswith("/*") and "(function () {" in script  # everything inside one function


@pytest.mark.parametrize("query", ["", "?b=", "?b=nobody", '?b=the-plug";alert(1)//'])
def test_embed_script_needs_an_existing_business(client, query):
    response = client.get("/embed.js" + query)
    assert response.status_code == 404
    assert "alert" not in response.text


def test_share_tab_offers_the_one_line_snippet_above_the_iframe(client):
    page = client.get("/owner/the-plug").text
    assert page.index('id="share-bubble"') < page.index('id="share-embed"')
    assert 'data-copy="share-bubble"' in page
    script = client.get("/static/owner.js").text
    assert '/embed.js?b=${encodeURIComponent(SLUG)}" async></script>' in script


def test_demo_site_carries_the_bubble(client):
    page = client.get("/demo/the-plug")
    assert page.status_code == 200
    assert "The Plug" in page.text and "<table>" in page.text
    assert '<script src="/embed.js?b=the-plug" async></script>' in page.text


def test_embed_script_closes_when_the_chat_asks(client):
    # The chat's own × (in ?embed=1) posts "jawab:close"; only messages from the bubble's iframe count.
    script = client.get("/embed.js?b=the-plug").text
    assert 'window.addEventListener("message"' in script
    assert '"jawab:close"' in script
    assert "event.source !== frame.contentWindow" in script
