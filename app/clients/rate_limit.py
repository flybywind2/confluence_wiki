from __future__ import annotations

import asyncio
from collections import deque
from functools import lru_cache


class MinuteRateLimiter:
    def __init__(self, limit: int, period_seconds: int = 60) -> None:
        self.limit = limit
        self.period_seconds = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                loop = asyncio.get_running_loop()
                now = loop.time()
                while self._timestamps and now - self._timestamps[0] >= self.period_seconds:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.limit:
                    self._timestamps.append(now)
                    return
                wait_time = self.period_seconds - (now - self._timestamps[0])
            await asyncio.sleep(max(wait_time, 0.01))


@lru_cache(maxsize=16)
def get_shared_rate_limiter(limit: int, period_seconds: int = 60) -> MinuteRateLimiter:
    return MinuteRateLimiter(limit=limit, period_seconds=period_seconds)
