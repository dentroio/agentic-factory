"""Run the sync Anthropic SDK off the asyncio event loop (AF-23)."""
from __future__ import annotations

import asyncio
from typing import Any


async def messages_create(client: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(client.messages.create, **kwargs)
