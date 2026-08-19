"""Guard: quality_gate's wait-healthy/smoke-test timeouts must not undercut
the wrapped scripts' own internal timeouts (AF-262 follow-up).

scripts/wait_healthy.sh defaults to a 300s retry loop. An external subprocess
timeout shorter than that kills the process mid-retry and reports a false
"CI tests failed" before the script's own timeout ever gets to fire — this
was the root cause behind WO-496/497/500/443/513/495 all parking on a
spurious gate failure despite passing when rerun manually.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_quality_gate():
    path = REPO_ROOT / "services" / "agent-runner" / "quality_gate.py"
    spec = importlib.util.spec_from_file_location("factory_quality_gate", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("proc", _stub_proc_module())
    spec.loader.exec_module(module)
    return module


def _stub_proc_module():
    import types

    async def communicate(proc, timeout):
        return await proc.communicate()

    stub = types.ModuleType("proc")
    stub.communicate = communicate
    return stub


def test_wait_healthy_timeout_exceeds_the_scripts_own_300s_default():
    g = _load_quality_gate()
    assert g._WAIT_HEALTHY_TIMEOUT > 300


def test_smoke_test_timeout_has_real_headroom():
    g = _load_quality_gate()
    # 60s gateway wait + several 10s per-endpoint checks under load
    assert g._SMOKE_TEST_TIMEOUT >= 180
