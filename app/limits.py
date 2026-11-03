"""Spending protection for the public demo (D-031): caps on how many messages reach the model.

Two limits:
- per visitor: a sliding window (e.g. at most 30 messages in any 60 minutes, per IP address);
- for everyone together: a daily cap (e.g. 1,000 messages per UTC day), so even many visitors
  can't spend more than a known amount a day.

Counters live in memory: they reset when the server restarts or sleeps, and they only work with
one server process. That's fine for a demo on one small free server.
"""

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timezone

HOUR = 3600


class RateLimiter:
    def __init__(self, per_visitor: int, per_day: int, window: float = HOUR,
                 clock: Callable[[], float] = time.time):
        self.per_visitor = per_visitor
        self.per_day = per_day
        self.window = window
        self.clock = clock  # injectable, so tests can move time forward without waiting
        self._visits: dict[str, deque[float]] = defaultdict(deque)
        self._day: str | None = None
        self._today = 0
        # Requests are handled in parallel threads (see main.py), so updates must not interleave.
        self._lock = threading.Lock()

    def check(self, visitor: str) -> str | None:
        """Count one message from `visitor`. Returns None if allowed, else a message for the visitor."""
        with self._lock:
            now = self.clock()
            day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            if day != self._day:
                self._day, self._today = day, 0
                self._visits.clear()  # also stops the dictionary growing forever

            if self._today >= self.per_day:
                return "The demo has reached its daily limit. Please come back tomorrow!"

            visits = self._visits[visitor]
            while visits and visits[0] <= now - self.window:
                visits.popleft()  # forget messages older than the window
            if len(visits) >= self.per_visitor:
                wait = math.ceil((visits[0] + self.window - now) / 60)  # whole minutes, rounded up
                return f"You've sent a lot of messages. Please try again in about {wait} minutes."

            visits.append(now)
            self._today += 1
            return None
