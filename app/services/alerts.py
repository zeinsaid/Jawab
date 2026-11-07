"""Who gets an email, and what it says. Routing follows the engine's handoff_reason (D-034):

| event                      | to                        |
|----------------------------|---------------------------|
| ask_owner                  | the owner (OWNER_ALERT_EMAIL) |
| handoff, complaint / lead  | the shop (SHOP_ALERT_EMAILS)  |
| handoff, other / abuse     | nobody                    |
| the model can't be reached | the owner, at most every 6 hours per deployment |
| the owner answers          | the customer, if they left an email, in their language |

Only businesses whose settings turn `alerts` / `email_customers` on send the first two and the
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
    },
    "el": {
        "subject": "Η ερώτησή σου στο {name}",
        "body": "Γεια σου,\n\nΡώτησες το {name}:\n“{question}”\n\nΗ απάντησή μας:\n{answer}\n",
        "footer": "Λαμβάνεις αυτό το email επειδή άφησες τη διεύθυνσή σου στη συνομιλία της ιστοσελίδας μας.",
    },
    "ar": {
        "subject": "سؤالك إلى {name}",
        "body": "مرحباً،\n\nسألتَ {name}:\n«{question}»\n\nإجابتنا:\n{answer}\n",
        "footer": "تصلك هذه الرسالة لأنك تركت بريدك الإلكتروني في دردشة موقعنا.",
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
                  inbox_url: str) -> bool:
        """The bot doesn't know: tell the owner, with a link to the inbox (never the key)."""
        text = (
            f"{business_name}'s assistant doesn't know the answer and is waiting for you.\n\n"
            f"Question: {question}\n"
            f"The customer wrote ({LANGUAGE_NAMES.get(language or 'en', language)}): {customer_text}\n\n"
            f"Answer it in the inbox whenever you like: {inbox_url}\n"
            "If the customer is still in the chat they'll see it there; if they left an email, "
            "it's emailed to them too, in their language."
        )
        return self.mailer.send(self.config.owner, self._subject(f"New question: {_short(question, 70)}"), text)

    def handoff(self, business_name: str, reason: str, summary: str, transcript: list[tuple[str, str]],
                customer_email: str | None) -> bool:
        """A complaint or a lead: tell the shop. Other reasons send nothing."""
        label = {"complaint": "Complaint", "lead": "Lead"}.get(reason)
        if label is None:
            return False
        lines = [f"{who}: {said}" for who, said in transcript]
        text = (
            f"A customer in {business_name}'s website chat needs a person ({label.lower()}).\n\n"
            f"Summary: {summary}\n\n"
            f"Customer's email: {customer_email or 'not given'}\n\n"
            "The conversation:\n" + "\n".join(lines) + "\n\n"
            "The customer was shown the shop's phone and WhatsApp numbers."
        )
        latest = next((said for who, said in reversed(transcript) if who == "Customer"), "")
        subject = f"[Jawab – {label}] {_short(latest, 70)}".rstrip()
        return self.mailer.send(self.config.shop, subject, text)

    def answer_to_customer(self, business_name: str, to: str, language: str | None, question: str,
                           answer: str, contact_line: str | None, reply_to: str | None) -> bool:
        lang = language if language in ANSWER_EMAIL else "en"
        template = ANSWER_EMAIL[lang]
        text = template["body"].format(name=business_name, question=question, answer=answer)
        if contact_line:
            text += f"\n{contact_line}\n"
        text += f"\n{business_name}\n\n— \n{template['footer']}\n"
        return self.mailer.send([to], template["subject"].format(name=business_name), text, reply_to=reply_to)

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
        return self.mailer.send(self.config.owner, self._subject(subject), text)

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


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
