"""Businesses: loading by slug, and one cached brain per (business, KB version). Spec section 5."""

import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Business
from brain.brain import Brain
from brain.kb import parse_kb
from brain.llm import LLMClient


def get_business(session: Session, slug: str) -> Business | None:
    return session.scalar(select(Business).where(Business.slug == slug))


class BrainCache:
    """Builds a Brain per business and KB version, sharing one LLM client.

    A saved KB change bumps `kb_version`, so the next message builds a fresh brain from the new KB.
    """

    def __init__(self, client: LLMClient):
        self.client = client
        self._brains: dict[int, tuple[int, Brain]] = {}  # business id -> (kb_version, brain)
        self._lock = threading.Lock()

    def get_brain(self, business: Business) -> Brain:
        with self._lock:
            cached = self._brains.get(business.id)
            if cached and cached[0] == business.kb_version:
                return cached[1]
            # A website chat: every message gets a reply, so no_reply is off (D-024).
            brain = Brain(parse_kb(business.kb_markdown), self.client, allow_no_reply=False)
            self._brains[business.id] = (business.kb_version, brain)
            return brain

    def forget(self, business_ids: list[int]) -> None:
        """Drop the brains of deleted businesses (expired sandboxes)."""
        with self._lock:
            for business_id in business_ids:
                self._brains.pop(business_id, None)
