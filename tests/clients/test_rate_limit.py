import asyncio

import pytest

from app.clients.confluence import ConfluenceClient
from app.clients.rate_limit import MinuteRateLimiter
from app.core.config import Settings


@pytest.mark.asyncio
async def test_rate_limiter_blocks_after_capacity():
    limiter = MinuteRateLimiter(limit=2, period_seconds=60)

    await limiter.acquire()
    await limiter.acquire()

    waiter = asyncio.create_task(limiter.acquire())
    await asyncio.sleep(0.05)

    assert waiter.done() is False
    waiter.cancel()


def test_confluence_clients_share_default_limiter(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)

    first = ConfluenceClient(settings)
    second = ConfluenceClient(settings)

    assert first.limiter is second.limiter
