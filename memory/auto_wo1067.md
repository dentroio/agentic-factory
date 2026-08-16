---
name: orchestrator-anthropic-calls-must-use-llm-client-wrapper
description: All Anthropic SDK message calls in orchestrator/intelligence must go through llm_client.messages_create, never client.messages.create directly
metadata:
  type: project
---

The orchestrator's `anthropic.Anthropic` client is synchronous, and calling `client.messages.create(...)` directly inside an `async def` handler blocks the asyncio event loop, stalling heartbeats and other concurrent orchestrator work. Fixed in WO-1067/AF-23 by adding `services/orchestrator/llm_client.py` with `async def messages_create(client, **kwargs)` that wraps the call in `asyncio.to_thread`.

**Why:** There's no obvious signal in the code that `client.messages.create` is blocking — it looks like a normal async-compatible call site until you check the SDK. A regression test (`tests/unit/test_llm_off_event_loop.py`) enforces this by asserting `orchestrator.py` and `intelligence.py` contain zero literal `.messages.create(` calls and always import/use `messages_create` instead.

**How to apply:** Any new code path that calls the Anthropic SDK's `messages