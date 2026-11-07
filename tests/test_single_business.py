"""Single-business mode (a business's own deployment, like The Plug's): nothing of the public demo is
served, only the one business exists, and its real settings apply. Plus the settings that differ
between the two modes, CORS for the website's bubble, and the env checks.

In-memory SQLite and a ScriptedClient: no model is called and the development database is never touched.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Business, make_engine, make_session_factory
from app.main import Deployment, create_app, deployment_from_env
from brain.llm import ScriptedClient

SINGLE = Deployment(mode="single", business="the-plug", name="Jawab – The Plug",
                    cors_origins=["https://theplug.cy"], cors_origin_regex=r"https://([a-z0-9-]+\.)?theplug\.pages\.dev")


@pytest.fixture
def single():
    engine = make_engine("sqlite://")
    return TestClient(create_app(engine, ScriptedClient([]), deployment=SINGLE)), make_session_factory(engine)


@pytest.mark.parametrize("method,path", [
    ("GET", "/"), ("GET", "/try"), ("GET", "/start"), ("GET", "/demo/the-plug"),
    ("POST", "/api/sandbox"), ("POST", "/api/onboarding"), ("GET", "/api/onboarding/00000000-0000-0000-0000-000000000000"),
    ("GET", "/api/public-stats/the-plug"), ("GET", "/static/index.html"), ("GET", "/static/start.html"),
    ("GET", "/static/try.js"), ("GET", "/static/landing.css"), ("GET", "/no-such-page"),
])
def test_the_public_demo_is_not_served(single, method, path):
    client, _ = single
    response = client.request(method, path, json={"business_name": "X", "mode": "quick"} if method == "POST" else None)
    assert response.status_code == 404
    assert "Try the demo" not in response.text  # the plain 404 page, not the demo's


@pytest.mark.parametrize("path", ["/b/the-plug", "/owner/the-plug", "/health", "/jawab.js", "/embed.js?b=the-plug",
                                  "/api/b/the-plug/public", "/static/chat.js", "/static/owner.js"])
def test_the_business_itself_is_served(single, path):
    client, _ = single
    assert client.get(path).status_code == 200


def test_only_the_one_business_exists(single):
    client, sessions = single
    with sessions() as session:
        assert [b.slug for b in session.scalars(select(Business))] == ["the-plug"]
        # Even if another business sat in the database, it wouldn't be reachable here.
        session.add(Business(slug="other", name="Other", owner_key="k" * 24, kb_markdown="x", settings={}))
        session.commit()
    for path in ("/b/other", "/owner/other", "/api/b/other/public", "/embed.js?b=other"):
        assert client.get(path).status_code == 404


def test_the_real_business_is_never_a_demo(single):
    client, sessions = single
    with sessions() as session:
        plug = session.scalar(select(Business).where(Business.slug == "the-plug"))
        assert plug.demo is False
        key = plug.owner_key
    headers = {"X-Owner-Key": key}
    assert client.get("/api/owner/the-plug/knowledge", headers=headers).json()["can_reset_demo"] is False
    assert client.post("/api/owner/the-plug/reset-demo", headers=headers).status_code == 404


def test_real_settings_where_it_runs_for_real_and_the_demo_overlay_on_the_demo(single):
    client, _ = single
    real = client.get("/api/b/the-plug/public").json()
    assert real["offline_message"]["en"].startswith("Chat is offline right now. Call us on 22 542659 (24/7)")
    assert real["email_capture"] is True
    assert real["suggestions"]["el"]  # live chips per page language, never the demo's pretend complaint
    assert "My prints came out in the wrong order!" not in str(real["suggestions"])

    demo = TestClient(create_app(make_engine("sqlite://"), ScriptedClient([]))).get("/api/b/the-plug/public").json()
    assert demo["offline_message"]["en"] == "The demo is offline for a moment. Please try again later."
    assert demo["email_capture"] is False
    for public in (real, demo):
        assert public["name"] == "The Plug"  # the short display name; the KB keeps the full one
        assert public["accent"] == "#F920EB"
        assert public["languages"] == ["en", "el", "ar"]  # replies, Arabic included
    assert real["ui_languages"] == ["en", "el"]  # the website's toggle, from the KB's ui_languages
    assert demo["ui_languages"] == ["en", "el", "ar"]  # the public demo keeps its Arabic showcase


def test_the_chat_page_wears_the_business_accent(single):
    client, _ = single
    page = client.get("/b/the-plug").text
    assert '<meta name="theme-color" content="#F920EB">' in page
    assert "<style>:root{--accent:" in page and "prefers-color-scheme: dark" in page
    assert "{{" not in page


def test_settings_are_rewritten_from_the_seed_on_every_start_but_the_kb_is_not():
    engine = make_engine("sqlite://")
    sessions = make_session_factory(engine)
    create_app(engine, ScriptedClient([]), deployment=SINGLE)
    with sessions() as session:
        plug = session.scalar(select(Business).where(Business.slug == "the-plug"))
        plug.settings = {"accent": "#000000"}
        plug.kb_markdown = plug.kb_markdown + "\n<!-- learned in production -->\n"
        session.commit()
    create_app(engine, ScriptedClient([]), deployment=SINGLE)  # a restart, or a deploy
    with sessions() as session:
        plug = session.scalar(select(Business).where(Business.slug == "the-plug"))
        assert plug.settings["accent"] == "#F920EB"
        assert plug.kb_markdown.endswith("<!-- learned in production -->\n")


def test_cors_lets_the_website_ping_health(single):
    client, _ = single
    for origin in ("https://theplug.cy", "https://abc123.theplug.pages.dev", "https://theplug.pages.dev"):
        response = client.get("/health", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == origin
    other = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_single_mode_needs_its_business_and_a_real_database(monkeypatch):
    monkeypatch.setenv("JAWAB_MODE", "single")
    monkeypatch.delenv("JAWAB_BUSINESS", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="JAWAB_BUSINESS"):
        deployment_from_env()
    monkeypatch.setenv("JAWAB_BUSINESS", "the-plug")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        deployment_from_env()
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("JAWAB_CORS_ORIGINS", "https://theplug.cy/, https://www.theplug.cy")
    deployment = deployment_from_env()
    assert deployment.single and deployment.business == "the-plug"
    assert deployment.cors_origins == ["https://theplug.cy", "https://www.theplug.cy"]
    monkeypatch.setenv("JAWAB_MODE", "solo")
    with pytest.raises(RuntimeError, match="multi"):
        deployment_from_env()


def test_an_unknown_single_business_fails_at_startup():
    with pytest.raises(ValueError, match="JAWAB_BUSINESS"):
        create_app(make_engine("sqlite://"), ScriptedClient([]), deployment=Deployment(mode="single", business="nobody"))


def test_ui_languages_come_from_the_kb_unless_a_setting_overrides_them():
    from app.services.settings import ui_languages
    assert ui_languages({"ui_languages": "en, el"}, ["en", "el", "ar"]) == ["en", "el"]
    assert ui_languages({}, ["en", "ar"]) == ["en", "ar"]  # no line: the reply languages
    assert ui_languages({"ui_languages": "en, de"}, ["en"]) == ["en"]  # only languages the page has labels for
    assert ui_languages({"ui_languages": "en, el"}, ["en"], ["en", "el", "ar"]) == ["en", "el", "ar"]
    assert ui_languages({"ui_languages": "de"}, ["de"]) == ["en"]


def test_the_embed_script_offers_the_websites_languages_where_it_runs_for_real(single):
    client, _ = single
    script = client.get("/embed.js?b=the-plug").text
    assert '"languages": ["en", "el"]' in script
    assert '"name": "The Plug"' in script and "22 542659" in script  # the real offline message
