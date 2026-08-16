"""Guards: Anthropic SDK calls must not block the orchestrator event loop (AF-23)."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH = REPO_ROOT / "services" / "orchestrator"


def _load_llm_client():
    spec = importlib.util.spec_from_file_location("llm_client", ORCH / "llm_client.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["llm_client"] = module
    spec.loader.exec_module(module)
    return module


def test_messages_create_runs_via_to_thread(monkeypatch):
    llm = _load_llm_client()
    seen: dict = {}

    async def fake_to_thread(fn, *args, **kwargs):
        seen["fn"] = fn
        seen["kwargs"] = kwargs
        return "off-loop"

    class _Messages:
        def create(self, **kwargs):
            raise AssertionError("sync create must not run on the event loop")

    class _Client:
        messages = _Messages()

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    client = _Client()
    result = asyncio.run(llm.messages_create(client, model="x", max_tokens=1))
    assert result == "off-loop"
    assert seen["fn"] == client.messages.create
    assert seen["kwargs"]["model"] == "x"


def test_orchestrator_and_intelligence_do_not_call_the_sdk_inline():
    orch = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    intel = (ORCH / "intelligence.py").read_text(encoding="utf-8")
    helper = (ORCH / "llm_client.py").read_text(encoding="utf-8")
    assert "client.messages.create" in helper
    assert "asyncio.to_thread" in helper
    for name, text in (("orchestrator.py", orch), ("intelligence.py", intel)):
        assert "from llm_client import messages_create" in text, name
        assert ".messages.create(" not in text, name
        assert "await messages_create(" in text, name
