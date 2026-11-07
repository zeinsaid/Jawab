"""Sending email: Resend's HTTP API, or nothing.

Render's free plan blocks the SMTP ports, so mail goes out over HTTPS. Plain text only: alerts and
answers are short, and plain text can't render wrong in any mail app.

A failed send is logged and swallowed: an email is never worth breaking a chat or an answer for.
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

log = logging.getLogger("jawab.mail")

RESEND_URL = "https://api.resend.com/emails"


class Mailer(Protocol):
    def send(self, to: list[str], subject: str, text: str, reply_to: str | None = None) -> bool: ...


class ResendMailer:
    def __init__(self, api_key: str, sender: str, http: httpx.Client | None = None):
        self.api_key = api_key
        self.sender = sender  # e.g. "The Plug <no-reply@theplug.cy>"
        self.http = http or httpx.Client(timeout=10)

    def send(self, to: list[str], subject: str, text: str, reply_to: str | None = None) -> bool:
        if not to:
            return False
        payload = {"from": self.sender, "to": to, "subject": subject, "text": text}
        if reply_to:
            payload["reply_to"] = reply_to
        try:
            response = self.http.post(RESEND_URL, json=payload,
                                      headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as e:
            log.warning("email not sent (%s): %s", type(e).__name__, subject)
            return False
        if response.status_code >= 400:
            # Until the sending domain is verified, Resend only delivers to the account's own address.
            log.warning("email not sent (Resend %s: %s): %s", response.status_code, response.text[:200], subject)
            return False
        log.info("email sent to %d recipient(s): %s", len(to), subject)
        return True


class NullMailer:
    """No RESEND_API_KEY: say what would have been sent, send nothing."""

    def send(self, to: list[str], subject: str, text: str, reply_to: str | None = None) -> bool:
        log.info("email not sent (no RESEND_API_KEY): %s", subject)
        return False


@dataclass
class RecordingMailer:
    """For tests: keeps every email instead of sending it."""

    sent: list[dict] = field(default_factory=list)

    def send(self, to: list[str], subject: str, text: str, reply_to: str | None = None) -> bool:
        self.sent.append({"to": list(to), "subject": subject, "text": text, "reply_to": reply_to})
        return True
