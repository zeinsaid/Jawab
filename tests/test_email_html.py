"""HTML emails (D-017): every email also has an HTML version in the business's colour, with anything
a customer typed escaped; and Zein's rule that every email to the shop also goes to the owner."""

from app.db import SEED_BUSINESSES
from app.services.alerts import AlertConfig, Alerts
from app.services.email_html import DEFAULT_ACCENT, Block, Email, render
from app.services.mail import RecordingMailer

CONFIG = AlertConfig(deployment="Jawab – The Plug", owner=["owner@example.com"],
                     shop=["shop@example.com", "manager@example.com"])


def alerts() -> tuple[Alerts, RecordingMailer]:
    mailer = RecordingMailer()
    return Alerts(mailer, CONFIG, session_factory=None), mailer


def test_a_lead_has_html_in_the_shops_colour_with_buttons_and_the_owner_in_cc():
    a, mailer = alerts()
    a.handoff("The Plug", "lead", "Wants 500 flyers <b>monthly</b>.",
              [("Customer", "Can you do 500 flyers a month? <script>x</script>"), ("Assistant", "Let me pass this on.")],
              "maria@example.com", "+357 99 123456", cc_owner=True, accent="#F920EB")
    sent = mailer.sent[0]
    assert sent["to"] == ["shop@example.com", "manager@example.com"] and sent["cc"] == ["owner@example.com"]
    html = sent["html"]
    assert "#F920EB" in html and "The Plug" in html
    assert 'href="mailto:maria@example.com"' in html and 'href="tel:+35799123456"' in html
    assert 'href="https://wa.me/35799123456"' in html
    # What the customer and the model wrote is shown, never run.
    assert "<script>" not in html and "&lt;script&gt;" in html and "&lt;b&gt;monthly" in html
    assert "Wants 500 flyers <b>monthly</b>." in sent["text"]  # plain text unchanged


def test_the_plugs_seed_copies_the_owner_on_shop_emails():
    # Zein's rule (D-017): every email from the website or Jawab to the shop or the manager also goes to him.
    plug = next(s for s in SEED_BUSINESSES if s["slug"] == "the-plug")
    assert plug["settings"]["cc_owner"] is True


def test_the_answer_email_is_right_to_left_in_arabic_and_keeps_the_text():
    a, mailer = alerts()
    a.answer_to_customer("The Plug", "c@example.com", "ar", "هل أنتم مفتوحون؟", "نعم، على مدار الساعة.",
                         None, "shop@example.com", accent="#F920EB")
    sent = mailer.sent[0]
    assert 'dir="rtl"' in sent["html"] and "إجابتنا" in sent["html"]
    assert "نعم، على مدار الساعة." in sent["text"]


def test_every_email_has_an_html_version():
    a, mailer = alerts()
    a.ask_owner("The Plug", "Open on Christmas?", "en", "are you open on xmas", "https://example.com/owner/the-plug")
    a.contact_left("The Plug", "complaint", "My prints were wrong", "c@example.com", None,
                   [("Customer", "My prints were wrong")], cc_owner=True)
    a.answer_to_customer("The Plug", "c@example.com", "el", "Ανοιχτά;", "Ναι.", "Για κάτι επείγον…", None)
    assert len(mailer.sent) == 3 and all(m["html"] and m["html"].startswith("<!doctype html>") for m in mailer.sent)


def test_a_dark_accent_keeps_the_name_readable_on_the_dark_header():
    dark = render(Email(brand="Shop", kicker="", title="t", accent=DEFAULT_ACCENT))
    bright = render(Email(brand="Shop", kicker="", title="t", accent="#F920EB",
                          blocks=[Block("Said", conversation=[("Customer", "hi")])]))
    assert 'color:#ffffff;">Shop</span>' in dark
    assert 'color:#F920EB;">Shop</span>' in bright
