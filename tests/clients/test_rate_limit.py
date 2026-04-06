import asyncio

import pytest

from app.clients.rate_limit import MinuteRateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_capacity():
    limiter = MinuteRateLimiter(limit=2, period_seconds=60)

    await limiter.acquire()
    await limiter.acquire()

    waiter = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0.05)

    assert waiter.done() is False
    waiter.cancel()
