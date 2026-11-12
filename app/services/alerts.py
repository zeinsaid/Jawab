"""Who gets an email, and what it says. Routing follows the engine's handoff_reason (D-034):

| event                      | to                        |
|----------------------------|---------------------------|
| ask_owner                  | the owner (OWNER_ALERT_EMAIL) |
| handoff, complaint / lead  | the shop (SHOP_ALERT_EMAILS), the owner in CC if `cc_owner` |
| the customer leaves a contact after one | the same people, as a "Re:" of that email (D-013) |
| handoff, other / abuse     | nobody                    |
| the model can't be reached | the owner, at most every 6 hours per deployment |
| the owner answers          | the customer, if they left an email, in their language |

Every email that goes to the shop also goes to the owner when the business sets `cc_owner` (The
Plug does: Zein's rule, D-017, for every email from the website or Jawab). Each email has a plain-text
version and an HTML one (app/services/email_html.py), in the business's accent colour.

Only businesses whose settings turn `alerts` / `email_customers` on send the first three and the
last; the offline alert belongs to the deployment and is always on when OWNER_ALERT_EMAIL is set.
Recipients come from env vars, never from the repo. These methods run as background tasks after
the response has gone out, and take plain values, not database rows.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db import AppState, utcnow
from app.services.email_html import Block, Email, render
from app.services.mail import Mailer

log = logging.getLogger("jawab.alerts")

OFFLINE_EVERY = timedelta(hours=6)
OFFLINE_KEY = "offline_alert_sent_at"
LANGUAGE_NAMES = {"en": "English", "el": "Greek", "ar": "Arabic"}


def split_addresses(value: str | None) -> list[str]:
    return [a.strip() for a in (value or "").split(",") if a.strip()]


@dataclass
class AlertConfig:
    deployment: str = "Jawab"  # the subject prefix: "Jawab demo", "Jawab – The Plug"
    owner: list[str] = field(default_factory=list)  # OWNER_ALERT_EMAIL
    shop: list[str] = field(default_factory=list)  # SHOP_ALERT_EMAILS


# --- Why the model call failed ---------------------------------------------------------------------

CAUSES = {
    "no_credit": "Out of OpenAI credit (insufficient_quota). Both deployments share one OpenAI balance, "
                 "so both are offline until credit is added in the OpenAI dashboard.",
    "rate_limited": "Rate-limited by OpenAI (429). It usually clears by itself within minutes.",
    "key_rejected": "OpenAI rejected the API key (401/403): revoked, restricted, or not allowed this model.",
    "provider_down": "OpenAI couldn't be reached or failed (timeout, connection error or a 5xx).",
    "other": "Another error.",
}


def classify(error: BaseException) -> str:
    """One of CAUSES' keys, from the provider SDK's exception (duck-typed: no SDK import needed)."""
    status = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        code = code or body.get("code") or (body.get("error") or {}).get("code")
    if code == "insufficient_quota" or "insufficient_quota" in str(error):
        return "no_credit"
    if status == 429:
        return "rate_limited"
    if status in (401, 403):
        return "key_rejected"
    name = type(error).__name__
    if (isinstance(status, int) and status >= 500) or "Timeout" in name or "Connection" in name:
        return "provider_down"
    return "other"


# --- The customer's answer email ---------------------------------------------------------------

ANSWER_EMAIL = {
    "en": {
        "subject": "Your question to {name}",
        "body": "Hi,\n\nYou asked {name}:\n“{question}”\n\nOur answer:\n{answer}\n",
        "footer": "You're getting this email because you left your address in our website chat.",
        "asked": "You asked",
        "answer": "Our answer",
    },
    "el": {
        "subject": "Η ερώτησή σου στο {name}",
        "body": "Γεια σου,\n\nΡώτησες το {name}:\n“{question}”\n\nΗ απάντησή μας:\n{answer}\n",
        "footer": "Λαμβάνεις αυτό το email επειδή άφησες τη διεύθυνσή σου στη συνομιλία της ιστοσελίδας μας.",
        "asked": "Ρώτησες",
        "answer": "Η απάντησή μας",
    },
    "ar": {
        "subject": "سؤالك إلى {name}",
        "body": "مرحباً،\n\nسألتَ {name}:\n«{question}»\n\nإجابتنا:\n{answer}\n",
        "footer": "تصلك هذه الرسالة لأنك تركت بريدك الإلكتروني في دردشة موقعنا.",
        "asked": "سؤالك",
        "answer": "إجابتنا",
    },
}


class Alerts:
    def __init__(self, mailer: Mailer, config: AlertConfig, session_factory: sessionmaker[Session]):
        self.mailer = mailer
        self.config = config
        self.session_factory = session_factory
        self._offline_lock = threading.Lock()

    def _subject(self, text: str) -> str:
        return f"[{self.config.deployment}] {text}"

    def ask_owner(self, business_name: str, question: str, language: str | None, customer_text: str,
                  inbox_url: str, accent: str | None = None) -> bool:
        """The bot doesn't know: tell the owner, with a link to the inbox (never the key)."""
        text = (
            f"{business_name}'s assistant doesn't know the answer and is waiting for you.\n\n"
            f"Question: {question}\n"
            f"The customer wrote ({LANGUAGE_NAMES.get(language or 'en', language)}): {customer_text}\n\n"
            f"Answer it in the inbox whenever you like: {inbox_url}\n"
            "If the customer is still in the chat they'll see it there; if they left an email, "
            "it's emailed to them too, in their language."
        )
        html = render(Email(
            brand=business_name, kicker="A question for you", title=question, accent=accent,
            actions=[("Answer in the inbox", inbox_url)],
            rows=[("Language", LANGUAGE_NAMES.get(language or "en", language or "en"))],
            blocks=[Block("The customer wrote", customer_text)],
            footer=["If the customer is still in the chat they'll see your answer there; if they left an email, "
                    "it's emailed to them too, in their language.", f"Sent by {self.config.deployment}."],
            preheader=customer_text[:120],
        ))
        return self.mailer.send(self.config.owner, self._subject(f"New question: {_short(question, 70)}"), text,
                                html=html)

    def _team(self, cc_owner: bool) -> tuple[list[str], list[str]]:
        """Who a complaint or lead goes to: the shop, with the owner in CC (once, and as the
        recipient if no shop address is set)."""
        shop = list(self.config.shop)
        owner = [a for a in self.config.owner if a not in shop] if cc_owner else []
        return (shop, owner) if shop else (owner, [])

    @staticmethod
    def handoff_subject(reason: str, customer_text: str) -> str:
        label = {"complaint": "Complaint", "lead": "Lead"}.get(reason, reason.title())
        return f"[Jawab – {label}] {_short(customer_text, 70)}".rstrip()

    def handoff(self, business_name: str, reason: str, summary: str, transcript: list[tuple[str, str]],
                customer_email: str | None, customer_phone: str | None = None, cc_owner: bool = False,
                asked: bool = False, accent: str | None = None) -> bool:
        """A complaint or a lead: tell the shop. Other reasons send nothing. `asked`: the chat is
        asking the customer for a contact (ask_contact), which then follows in this thread."""
        if reason not in ("complaint", "lead"):
            return False
        lines = [f"{who}: {said}" for who, said in transcript]
        reach = _reach(customer_email, customer_phone)
        if asked and not (customer_email or customer_phone):
            reach = ("How to reach the customer: not known yet. The chat has asked them for an email or "
                     "WhatsApp number; if they leave one, it follows as a reply in this thread.")
        text = (
            f"A customer in {business_name}'s website chat needs a person ({reason}).\n\n"
            f"Summary: {summary}\n\n"
            + reach
            + "\n\nThe conversation:\n" + "\n".join(lines) + "\n\n"
            "The customer was shown the shop's phone and WhatsApp numbers."
        )
        latest = next((said for who, said in reversed(transcript) if who == "Customer"), "")
        waiting = asked and not (customer_email or customer_phone)
        html = render(Email(
            brand=business_name, kicker=_label(reason), title="A customer in the website chat needs a person",
            accent=accent, actions=_actions(customer_email, customer_phone),
            rows=_reach_rows(customer_email, customer_phone, waiting),
            blocks=[Block("Summary", summary), Block("The conversation", conversation=transcript)],
            footer=["The customer was shown the shop's phone and WhatsApp numbers.",
                    f"Sent by {self.config.deployment}."],
            preheader=summary[:120],
        ))
        to, cc = self._team(cc_owner)
        return self.mailer.send(to, self.handoff_subject(reason, latest), text, reply_to=customer_email, cc=cc,
                                html=html)

    def contact_left(self, business_name: str, reason: str, customer_text: str, customer_email: str | None,
                     customer_phone: str | None, transcript: list[tuple[str, str]], cc_owner: bool = False,
                     accent: str | None = None) -> bool:
        """The customer left a way to reach them after a complaint or lead was emailed: a reply to
        that email (same subject), so it lands in the same thread."""
        lines = [f"{who}: {said}" for who, said in transcript]
        text = (
            f"The customer from this {reason} in {business_name}'s website chat left a way to reach them.\n\n"
            + _reach(customer_email, customer_phone)
            + "\n\nThe conversation so far:\n" + "\n".join(lines) + "\n"
        )
        html = render(Email(
            brand=business_name, kicker=_label(reason), title="The customer left a way to reach them",
            accent=accent, actions=_actions(customer_email, customer_phone),
            rows=_reach_rows(customer_email, customer_phone, False),
            blocks=[Block("The conversation so far", conversation=transcript)],
            footer=[f"Sent by {self.config.deployment}."],
            preheader="The customer left a way to reach them.",
        ))
        to, cc = self._team(cc_owner)
        subject = "Re: " + self.handoff_subject(reason, customer_text)
        return self.mailer.send(to, subject, text, reply_to=customer_email, cc=cc, html=html)

    def answer_to_customer(self, business_name: str, to: str, language: str | None, question: str,
                           answer: str, contact_line: str | None, reply_to: str | None,
                           accent: str | None = None) -> bool:
        lang = language if language in ANSWER_EMAIL else "en"
        template = ANSWER_EMAIL[lang]
        text = template["body"].format(name=business_name, question=question, answer=answer)
        if contact_line:
            text += f"\n{contact_line}\n"
        text += f"\n{business_name}\n\n— \n{template['footer']}\n"
        subject = template["subject"].format(name=business_name)
        html = render(Email(
            brand=business_name, kicker="", title=subject, accent=accent, lang=lang,
            blocks=[Block(template["asked"], question), Block(template["answer"], answer)],
            footer=[line for line in (contact_line, template["footer"]) if line],
            preheader=answer[:120],
        ))
        return self.mailer.send([to], subject, text, reply_to=reply_to, html=html)

    def offline(self, cause: str, detail: str = "") -> bool:
        """The model can't be reached. At most one email every OFFLINE_EVERY per deployment; the
        time of the last one is in the database, so it survives a restart where the DB does."""
        if not self.config.owner:
            return False
        with self._offline_lock:
            try:
                if not self._claim_offline_slot():
                    return False
            except Exception:  # the database may be what's down; still say so, once per process
                log.exception("couldn't check the offline alert's last time")
                if getattr(self, "_sent_without_db", False):
                    return False
                self._sent_without_db = True
        text = (
            f"{self.config.deployment} can't reach the model, so the chat is showing its offline message.\n\n"
            f"Why: {CAUSES.get(cause, CAUSES['other'])}\n"
            + (f"Details: {detail}\n" if detail else "")
            + f"\nYou'll get at most one of these every {int(OFFLINE_EVERY.total_seconds() // 3600)} hours."
        )
        subject = "Out of OpenAI credit: the chat is offline" if cause == "no_credit" else "The chat is offline"
        html = render(Email(
            brand=self.config.deployment, kicker="Alert", title=subject,
            banner="The chat is showing its offline message.",
            rows=[("Why", CAUSES.get(cause, CAUSES["other"]))] + ([("Details", detail)] if detail else []),
            footer=[f"You'll get at most one of these every {int(OFFLINE_EVERY.total_seconds() // 3600)} hours."],
            preheader=CAUSES.get(cause, CAUSES["other"])[:120],
        ))
        return self.mailer.send(self.config.owner, self._subject(subject), text, html=html)

    def _claim_offline_slot(self) -> bool:
        now = utcnow()
        with self.session_factory() as session:
            row = session.scalar(select(AppState).where(AppState.key == OFFLINE_KEY))
            if row is not None:
                last = datetime.fromisoformat(row.value)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if now - last < OFFLINE_EVERY:
                    return False
                row.value = now.isoformat()
            else:
                session.add(AppState(key=OFFLINE_KEY, value=now.isoformat()))
            session.commit()
        return True


def _reach(email: str | None, phone: str | None) -> str:
    """How the team can reach the customer, as the alert emails say it."""
    lines = []
    if phone:
        lines.append(f"Customer's WhatsApp / phone: {phone}")
    if email:
        lines.append(f"Customer's email: {email} (reply to this email to write to them)")
    return "\n".join(lines) or "Customer's email: not given"


def _label(reason: str) -> str:
    return {"complaint": "Complaint", "lead": "Lead"}.get(reason, reason.title())


def _reach_rows(email: str | None, phone: str | None, waiting: bool) -> list[tuple[str, str]]:
    """How to reach the customer, as rows of the HTML email."""
    rows = []
    if phone:
        rows.append(("WhatsApp / phone", phone))
    if email:
        rows.append(("Email", f"{email} (reply to this email to write to them)"))
    if not rows:
        rows.append(("How to reach them",
                     "Not known yet. The chat has asked for an email or WhatsApp number; if they leave one, "
                     "it follows as a reply in this thread." if waiting else "Not given"))
    return rows


def _actions(email: str | None, phone: str | None) -> list[tuple[str, str]]:
    """One-tap buttons: write to the customer, call them, message them on WhatsApp."""
    actions = []
    if email:
        actions.append(("Reply by email", f"mailto:{email}"))
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if phone and len(digits) >= 6:
        actions.append(("Call", "tel:" + ("+" if phone.strip().startswith("+") else "") + digits))
        actions.append(("WhatsApp", f"https://wa.me/{digits}"))
    return actions


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
