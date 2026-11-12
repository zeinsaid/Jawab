"""Per-business settings: what the chat looks like and does beyond the knowledge base.

The KB says what the bot knows; these say how the product around it behaves for one business:
its accent colour, the message shown when the chat is offline, the contact line under replies that
need a person, whether customers can leave an email or a number, whether anyone gets alerts, and
whether handed-off chats wait in the inbox or go to the team by email.

Settings are configuration, not data. A seeded business gets them from its seed (app/db.py), and
they're written again on every startup, so a deploy changes them. The KB and the conversations are
data: the database is their source of truth and startup never overwrites them.

On the public demo (multi-business mode) every demo business and sandbox gets DEMO_OVERLAY on top:
no real contacts, no emails to customers, no alerts. Otherwise a visitor could set any address as
"their" email, answer as the sandbox owner and make the shop's domain send whatever they typed.
"""

import re

from app.db import Business

LANGS = ("en", "el", "ar")  # the languages Jawab's pages have labels for

GENERIC_OFFLINE = {
    "en": "Chat is offline right now. Please try again later.",
    "el": "Η συνομιλία δεν είναι διαθέσιμη αυτή τη στιγμή. Δοκίμασε ξανά αργότερα.",
    "ar": "الدردشة غير متاحة الآن. يرجى المحاولة لاحقاً.",
}

DEMO_OFFLINE = {
    "en": "The demo is offline for a moment. Please try again later.",
    "el": "Η επίδειξη δεν είναι διαθέσιμη για λίγο. Δοκίμασε ξανά αργότερα.",
    "ar": "العرض التجريبي غير متاح للحظات. يرجى المحاولة لاحقاً.",
}

DEFAULTS = {
    "display_name": None,  # the short name customers see ("The Plug"); None shows the KB's business name
    "accent": None,  # a "#RRGGBB" colour for the bubble and the chat page; None keeps Jawab's teal
    "offline_message": GENERIC_OFFLINE,  # {lang: text}, shown when the model or the server is down
    "contact_line": None,  # {lang: text} under ask_owner and handoff replies (not abuse); None for none
    "reply_to": None,  # where a customer's reply to an answer email goes (the shop's inbox)
    "alerts": False,  # email the owner (ask_owner) and the shop (complaints, leads)
    "email_customers": False,  # offer "leave your email" and email the owner's answer
    "ui_languages": None,  # overrides the KB's ui_languages line for the page's toggle; None follows the KB
    # What a handoff (other than abuse) does, D-013. "inbox": a person replies in the owner's inbox,
    # and the bot stays quiet until it's given back. "notify": the team is told by email (complaints,
    # leads) and handles it outside Jawab; the inbox only records it, and the bot carries on.
    "handoffs": "inbox",
    "ask_contact": False,  # after a complaint or lead: "leave your email or WhatsApp number"
    "cc_owner": False,  # copy the owner on the shop's complaint and lead emails
    # Delete a conversation after this many days without activity (app/services/retention.py,
    # D-016); None keeps conversations.
    "retention_days": None,
}

HANDOFF_MODES = ("inbox", "notify")

DEMO_OVERLAY = {
    # The public demo shows off all three page languages, Arabic included, whatever the real shop's
    # website offers (its KB says ui_languages: en, el).
    "ui_languages": list(LANGS),
    "offline_message": DEMO_OFFLINE,
    "contact_line": None,
    "reply_to": None,
    "alerts": False,
    "email_customers": False,
    # A sandbox owner tries the inbox's "reply as the team" flow, so the demo keeps it.
    "handoffs": "inbox",
    "ask_contact": False,
    "cc_owner": False,
}

ACCENT = re.compile(r"^#[0-9a-fA-F]{6}$")


def seed_settings(seed: dict, demo: bool) -> dict:
    """The settings a seeded business gets: its seed's, with the demo overlay on the public demo."""
    settings = {**DEFAULTS, **seed.get("settings", {})}
    return {**settings, **DEMO_OVERLAY} if demo else settings


def effective(business: Business) -> dict:
    """The business's settings with defaults filled in. A bad accent is dropped, never served."""
    settings = {**DEFAULTS, **(business.settings or {})}
    if settings["accent"] and not ACCENT.match(str(settings["accent"])):
        settings["accent"] = None
    if settings["handoffs"] not in HANDOFF_MODES:
        settings["handoffs"] = "inbox"
    if business.demo or business.sandbox_of:  # belt and braces: a demo copy never goes live
        settings.update(DEMO_OVERLAY)
    return settings


def display_name(business: Business) -> str:
    """What the chat calls the business: its short display name, else its full name."""
    return (business.settings or {}).get("display_name") or business.name


def pick(texts: dict | None, lang: str | None) -> str | None:
    """One text from a {lang: text} setting: the language asked for, else English."""
    if not texts:
        return None
    return texts.get(lang or "en") or texts.get("en")


def ui_languages(kb_metadata: dict, reply_languages: list[str], override: list[str] | None = None) -> list[str]:
    """The languages the chat page offers in its toggle: a settings override (the demo's), else the
    KB's `ui_languages:` line, else its reply languages, limited to those the page has labels for.
    The bot still replies in whatever language a customer writes; this only changes the page's labels."""
    raw = kb_metadata.get("ui_languages") or ""
    listed = (list(override or []) or [code.strip() for code in raw.split(",") if code.strip()]
              or list(reply_languages))
    offered = [code for code in listed if code in LANGS]
    return offered or ["en"]
