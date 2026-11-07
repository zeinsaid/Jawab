"""The floating chat bubble: the loader (/jawab.js, self-hosted by websites), /embed.js (the same file with
a business's defaults filled in), the Share tab snippet and the demo shop website.

In-memory SQLite and a ScriptedClient: no model is called and the development database is never touched.
"""

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.db import make_engine
from app.main import create_app
from brain.llm import ScriptedClient


@pytest.fixture
def client():
    return TestClient(create_app(make_engine("sqlite://"), ScriptedClient([])))


def defaults_in(script: str) -> dict:
    match = re.search(r"var DEFAULTS = (\{.*?\});\n", script)
    assert match, "the DEFAULTS line is missing"
    return json.loads(match.group(1))


def test_the_self_hosted_loader_has_no_server_values(client):
    # A website hosts this file itself: everything comes from the script tag's data- attributes.
    response = client.get("/jawab.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    script = response.text
    assert "var DEFAULTS = /*__JAWAB_DEFAULTS__*/{};" in script
    for name in ('attr("base")', 'attr("business")', 'attr("accent")', 'attr("name")', 'attr("languages")',
                 'attr("offline-" + LANG)'):
        assert name in script
    assert script.lstrip().startswith("/*") and "(function () {" in script  # everything inside one function
    assert client.get("/static/jawab.js").text == script


def test_embed_script_is_the_loader_with_the_business_filled_in(client):
    response = client.get("/embed.js?b=the-plug")
    assert response.status_code == 200
    script = response.text
    assert "__JAWAB_DEFAULTS__" not in script
    defaults = defaults_in(script)
    assert defaults["business"] == "the-plug" and defaults["base"] == "http://testserver"
    assert defaults["accent"] == "#F920EB"
    assert defaults["languages"] == ["en", "el", "ar"]  # the public demo shows all three page languages
    # On the public demo, the demo's offline message: never the real shop's phone numbers.
    assert defaults["offline"]["en"] == "The demo is offline for a moment. Please try again later."


@pytest.mark.parametrize("query", ["", "?b=", "?b=nobody", '?b=the-plug";alert(1)//'])
def test_embed_script_needs_an_existing_business(client, query):
    response = client.get("/embed.js" + query)
    assert response.status_code == 404
    assert "alert" not in response.text


def test_the_loader_follows_the_page_language_and_hands_over_to_the_chat(client):
    script = client.get("/jawab.js").text
    # The host page's <html lang> picks the language, passed to the chat in the URL...
    assert 'document.documentElement.getAttribute("lang")' in script
    assert '"?embed=1&lang=" + encodeURIComponent(LANG)' in script
    # ...where it wins over whatever the chat stored itself.
    chat = client.get("/static/chat.js").text
    assert 'let lang = UI_LANGS.includes(URL_LANG) ? URL_LANG : UI_LANGS.includes(load(LANG_KEY))' in chat
    # It wakes the server on page load, shows a local greeting at once, and waits about a minute.
    assert 'BASE + "/health"' in script and "health(70000)" in script
    assert "var WAKE_MS = 60000;" in script
    assert 'list.appendChild(el("li", "jw-m jw-bot", WELCOME));' in script
    # The hand-over protocol, on both sides; only messages from the bubble's own iframe count.
    assert "event.source !== frame.contentWindow" in script
    for kind in ("jawab:ready", "jawab:failed", "jawab:conversation", "jawab:close"):
        assert f'"{kind}"' in script and f'type: "{kind}"' in chat
    assert '{ type: "jawab:send", text: pending }' in script and '"jawab:send"' in chat
    # The conversation lives in the website's own storage and comes back as ?c=.
    assert 'url += "&c=" + encodeURIComponent(conversation)' in script
    assert 'PARAMS.get("c")' in chat


def test_the_local_greeting_matches_the_chat_page(client):
    # The swap from the loader's stand-in to the real chat must not change the greeting.
    script = client.get("/jawab.js").text
    chat = client.get("/static/chat.js").text
    for welcome in re.findall(r'^      welcome: (".*?"),$', script, re.M):
        assert f"    welcome: {welcome}," in chat


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
