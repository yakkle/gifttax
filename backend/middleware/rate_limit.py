"""Bounded, thread-safe request limits for a single application process."""

from collections import OrderedDict, deque
from threading import Lock
from time import monotonic


class RateLimiter:
    def __init__(self, per_client: int = 30, total: int = 120) -> None:
        self.per_client, self.total = per_client, total
        self.clients: OrderedDict[str, deque] = OrderedDict()
        self.requests: deque = deque()
        self.lock = Lock()

    def allow(self, client: str, *, now: float | None = None) -> bool:
        now = monotonic() if now is None else now
        with self.lock:
            while self.requests and self.requests[0] <= now - 60:
                self.requests.popleft()
            history = self.clients.setdefault(client, deque())
            self.clients.move_to_end(client)
            while history and history[0] <= now - 60:
                history.popleft()
            if len(self.clients) > 2048:
                self.clients.popitem(last=False)
            if len(history) >= self.per_client or len(self.requests) >= self.total:
                return False
            history.append(now)
            self.requests.append(now)
            return True
