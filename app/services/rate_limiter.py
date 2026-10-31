import time
from collections import deque
from collections.abc import Callable

# Forget idle clients once this many are tracked, so memory stays bounded
MAX_TRACKED_CLIENTS = 10_000


class SlidingWindowRateLimiter:
    """
    In-memory sliding-window rate limiter keyed by client (e.g. IP address).

    State lives in the process, which suits a single-instance demo: it resets
    on restart and is not shared between workers.
    """

    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}

    def hit(self, key: str) -> float | None:
        """
        Records an event for `key` if the client is under its limit.

        Returns None when the event is allowed, otherwise the number of seconds
        until the client may try again. A non-positive limit disables limiting.
        """
        if self.max_events <= 0:
            return None

        now = self._clock()
        cutoff = now - self.window_seconds
        events = self._events.setdefault(key, deque())
        while events and events[0] <= cutoff:
            events.popleft()

        if len(events) >= self.max_events:
            return events[0] + self.window_seconds - now

        events.append(now)
        if len(self._events) > MAX_TRACKED_CLIENTS:
            self._forget_idle(cutoff)
        return None

    def _forget_idle(self, cutoff: float) -> None:
        idle = [key for key, events in self._events.items() if not events or events[-1] <= cutoff]
        for key in idle:
            del self._events[key]
