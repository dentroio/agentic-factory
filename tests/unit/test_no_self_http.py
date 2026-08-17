"""Guards: orchestrator must not HTTP-round-trip to itself (WO-1077)."""
from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "services" / "orchestrator" / "orchestrator.py"


def test_orchestrator_does_not_http_to_its_own_port():
    text = ORCH.read_text(encoding="utf-8")
    assert "localhost:{API_PORT}" not in text
    assert "127.0.0.1:{API_PORT}" not in text
    assert "await pm_dispatch_wo(" in text
    assert "await reset_dispatch(" in text
    assert "await get_backends()" in text
