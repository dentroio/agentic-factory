"""Conflict advisor: service parsing, deterministic edges, cycle refusal, LLM JSON."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "services" / "orchestrator"


def _load():
    spec = importlib.util.spec_from_file_location("conflict_advisor", ORCH / "conflict_advisor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_services_splits_and_drops_docs_none():
    adv = _load()
    assert adv.parse_service_tokens("frontend | data-service") == {"frontend", "data-service"}
    assert adv.parse_service_tokens("orchestrator, docs") == {"orchestrator"}
    assert adv.parse_service_tokens("none") == set()
    assert adv.parse_services_from_spec("**Services:** frontend and gateway\n") == {
        "frontend", "gateway",
    }


def test_order_pair_priority_then_number():
    adv = _load()
    p1 = {"number": 500, "priority": "P1"}
    p2 = {"number": 100, "priority": "P2"}
    earlier, later = adv.order_pair(p1, p2)
    assert earlier is p1 and later is p2
    a = {"number": 418, "priority": "P2"}
    b = {"number": 463, "priority": "P2"}
    earlier, later = adv.order_pair(a, b)
    assert earlier["number"] == 418 and later["number"] == 463


def test_deterministic_edge_for_shared_service():
    adv = _load()
    wos = [
        {"wo": "WO-418", "number": 418, "priority": "P2", "services": "frontend",
         "files_likely_changed": [], "depends_on": []},
        {"wo": "WO-463", "number": 463, "priority": "P2", "services": "frontend",
         "files_likely_changed": [], "depends_on": []},
    ]
    edges = adv.propose_deterministic_edges(wos, {})
    assert len(edges) == 1
    assert edges[0]["later"] == "WO-463"
    assert edges[0]["earlier"] == 418
    assert "frontend" in edges[0]["reason"]


def test_docs_only_does_not_mutex():
    adv = _load()
    wos = [
        {"wo": "WO-1", "number": 1, "priority": "P3", "services": "docs",
         "files_likely_changed": [], "depends_on": []},
        {"wo": "WO-2", "number": 2, "priority": "P2", "services": "frontend",
         "files_likely_changed": [], "depends_on": []},
    ]
    assert adv.propose_deterministic_edges(wos, {}) == []


def test_shared_file_edge():
    adv = _load()
    wos = [
        {"wo": "WO-10", "number": 10, "priority": "P2", "services": "none",
         "files_likely_changed": ["src/foo.py"], "depends_on": []},
        {"wo": "WO-11", "number": 11, "priority": "P2", "services": "none",
         "files_likely_changed": ["src/foo.py"], "depends_on": []},
    ]
    edges = adv.propose_deterministic_edges(wos, {})
    assert edges[0]["later"] == "WO-11"
    assert "foo.py" in edges[0]["reason"]


def test_refuses_cycle_against_spec_depends():
    adv = _load()
    wos = [
        {"wo": "WO-418", "number": 418, "priority": "P2", "services": "frontend",
         "files_likely_changed": [], "depends_on": [463]},
        {"wo": "WO-463", "number": 463, "priority": "P2", "services": "frontend",
         "files_likely_changed": [], "depends_on": []},
    ]
    # Spec already says 418 waits for 463. Advisor must not add 463 → 418.
    edges = adv.propose_deterministic_edges(wos, {})
    assert all(not (e["later"] == "WO-463" and e["earlier"] == 418) for e in edges)


def test_skips_existing_advisor_edge():
    adv = _load()
    wos = [
        {"wo": "WO-418", "number": 418, "priority": "P2", "services": "frontend",
         "files_likely_changed": [], "depends_on": []},
        {"wo": "WO-463", "number": 463, "priority": "P2", "services": "frontend",
         "files_likely_changed": [], "depends_on": []},
    ]
    assert adv.propose_deterministic_edges(wos, {"WO-463": [418]}) == []


def test_parse_llm_edges_high_confidence_only():
    adv = _load()
    text = """```json
{"edges":[
  {"later":"WO-463","earlier":"WO-418","reason":"same page","confidence":"high"},
  {"later":"WO-500","earlier":"WO-418","reason":"maybe","confidence":"medium"},
  {"later":"WO-999","earlier":"WO-418","reason":"invented","confidence":"high"}
]}
```"""
    edges = adv.parse_llm_edges(text, allowed_nums={418, 463, 500})
    assert len(edges) == 1
    assert edges[0]["later"] == "WO-463"
    assert edges[0]["earlier"] == 418


def test_parse_llm_edges_bad_json():
    adv = _load()
    assert adv.parse_llm_edges("not json", {1}) == []


def test_merge_edges_skips_held_wos():
    adv = _load()
    open_by = {
        "WO-583": {"wo": "WO-583", "number": 583, "priority": "P1", "services": "docs",
                   "files_likely_changed": [], "depends_on": []},
        "WO-588": {"wo": "WO-588", "number": 588, "priority": "P1", "services": "docs",
                   "files_likely_changed": [], "depends_on": []},
    }
    proposed = [{"later": "WO-583", "earlier": 588, "reason": "shared", "source": "deterministic"}]
    accepted = adv.merge_edges(proposed, [], {}, open_by, held_wos={"WO-588"})
    assert accepted == []


def test_merge_edges_caps_fan_in():
    adv = _load()
    open_by = {
        f"WO-{n}": {"wo": f"WO-{n}", "number": n, "priority": "P1", "services": "docs",
                    "files_likely_changed": [], "depends_on": []}
        for n in (583, 584, 585, 586)
    }
    proposed = [
        {"later": "WO-586", "earlier": 583, "reason": "a", "source": "deterministic"},
        {"later": "WO-586", "earlier": 584, "reason": "b", "source": "deterministic"},
        {"later": "WO-586", "earlier": 585, "reason": "c", "source": "deterministic"},
    ]
    accepted = adv.merge_edges(proposed, [], {}, open_by, max_fan_in=2)
    assert len(accepted) == 2
    assert {e["earlier"] for e in accepted} == {583, 584}


def test_merge_edges_caps_total_edges():
    adv = _load()
    open_by = {
        f"WO-{n}": {"wo": f"WO-{n}", "number": n, "priority": "P2", "services": "frontend",
                    "files_likely_changed": [], "depends_on": []}
        for n in range(100, 110)
    }
    proposed = [
        {"later": f"WO-{later}", "earlier": earlier, "reason": "x", "source": "deterministic"}
        for earlier, later in zip(range(100, 109), range(101, 110))
    ]
    accepted = adv.merge_edges(proposed, [], {}, open_by, max_edges=3)
    assert len(accepted) == 3


def test_orchestrator_unions_advisor_depends():
    text = (ORCH / "orchestrator.py").read_text(encoding="utf-8")
    get_next = text.split("async def get_next")[1].split("async def ")[0]
    assert "_effective_depends" in get_next
    assert "services_in_flight" in get_next
    assert "conflict_advisor" in text
    assert "_run_conflict_advisor" in text
    assert "conflict_advisor.json" in text
    assert "held_wos" in text
    assert "PM_DISPATCH_TTL_SECONDS" in text
    assert "/api/stalls" in text
