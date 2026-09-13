"""WO-1097: Doc Writer survives empty Claude responses."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "doc_writer.py"


def _load_doc_writer():
    spec = importlib.util.spec_from_file_location("doc_writer_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_call_claude_returns_empty_string_when_no_text_blocks(monkeypatch):
    dw = _load_doc_writer()

    class FakeMessages:
        def create(self, **kwargs):
            return SimpleNamespace(content=[], stop_reason="end_turn")

    class FakeAnthropic:
        def __init__(self, api_key=""):
            self.messages = FakeMessages()

    fake_anthropic = SimpleNamespace(Anthropic=FakeAnthropic)
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    assert dw.call_claude("sys", "user") == ""
