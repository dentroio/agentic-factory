"""Conflict advisor — extra depends_on edges and same-service dispatch skip.

Dispatch itself stays rule-based (`/api/next`). This module:

1. Parses `**Services:**` from WO specs (deterministic mutex vs in-flight work).
2. Proposes `depends_on` edges when two *open* WOs share a service or a declared
   file, so they cannot run in an order that fights.
3. Optionally asks the factory LLM for extra high-confidence edges the spec
   author did not write down.

Edges are stored by the orchestrator in `/data/conflict_advisor.json` and
unioned at claim time. Spec files are never rewritten.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Iterable

IGNORE_SERVICES = frozenset({
    "", "none", "n/a", "na", "-", "docs", "doc", "documentation",
})

_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

_SERVICES_LINE = re.compile(r"\*\*Services:\*\*\s*([^\n]+)", re.IGNORECASE)


def parse_service_tokens(raw: str | Iterable[str] | None) -> set[str]:
    """Normalize a Services field to a set of service names.

    Splits on comma, pipe, slash, or the word 'and'. Drops docs/none placeholders
    so a docs-only WO does not mutex the whole factory.
    """
    if raw is None:
        return set()
    if not isinstance(raw, str):
        raw = ",".join(str(x) for x in raw)
    parts = re.split(r"[,;/|]|\band\b", raw, flags=re.IGNORECASE)
    out: set[str] = set()
    for p in parts:
        tok = p.strip().lower()
        tok = re.sub(r"\s+", "-", tok)
        if tok in IGNORE_SERVICES or not tok:
            continue
        out.add(tok)
    return out


def parse_services_from_spec(content: str) -> set[str]:
    m = _SERVICES_LINE.search(content or "")
    if not m:
        return set()
    return parse_service_tokens(m.group(1))


def service_set_from_spec(spec: dict | None) -> set[str]:
    spec = spec or {}
    if spec.get("services"):
        return parse_service_tokens(spec["services"])
    return parse_services_from_spec(spec.get("_raw_body") or "")


def wo_num(wo_id: str | int) -> int | None:
    raw = str(wo_id or "").strip().upper()
    if raw.startswith("WO-"):
        raw = raw[3:]
    return int(raw) if raw.isdigit() else None


def wo_id_for(num: int) -> str:
    return f"WO-{num}"


def _priority_key(priority: str) -> int:
    return _PRIORITY_ORDER.get((priority or "P2").strip().upper(), 9)


def order_pair(a: dict, b: dict) -> tuple[dict, dict]:
    """Return (earlier, later). Higher priority runs first; same priority → lower number."""
    pa, pb = _priority_key(a.get("priority", "P2")), _priority_key(b.get("priority", "P2"))
    na, nb = int(a["number"]), int(b["number"])
    if pa != pb:
        return (a, b) if pa < pb else (b, a)
    return (a, b) if na < nb else (b, a)


def overlap_reason(a: dict, b: dict) -> str | None:
    sa, sb = service_set_from_spec(a), service_set_from_spec(b)
    shared_svc = sorted(sa & sb)
    fa = set(a.get("files_likely_changed") or [])
    fb = set(b.get("files_likely_changed") or [])
    shared_files = sorted(fa & fb)
    if shared_svc:
        return f"shared service(s): {', '.join(shared_svc)}"
    if shared_files:
        shown = ", ".join(shared_files[:4])
        extra = f" (+{len(shared_files) - 4} more)" if len(shared_files) > 4 else ""
        return f"shared file(s): {shown}{extra}"
    return None


def graph_from(open_wos: list[dict], advisor_edges: dict[str, list[int]]) -> dict[str, list[int]]:
    g: dict[str, list[int]] = {k: list(v) for k, v in (advisor_edges or {}).items()}
    for w in open_wos:
        wid = w.get("wo") or wo_id_for(int(w["number"]))
        for d in w.get("depends_on") or []:
            n = d if isinstance(d, int) else wo_num(d)
            if n is None:
                continue
            bucket = g.setdefault(wid, [])
            if n not in bucket:
                bucket.append(n)
    return g


def existing_depends(wo: dict, advisor_edges: dict[str, list[int]]) -> set[int]:
    nums: set[int] = set()
    for d in wo.get("depends_on") or []:
        n = d if isinstance(d, int) else wo_num(d)
        if n is not None:
            nums.add(n)
    wo_key = wo.get("wo") or wo_id_for(int(wo["number"]))
    for n in advisor_edges.get(wo_key, []) or []:
        nums.add(int(n))
    return nums


def depends_reaches(edges: dict[str, list[int]], from_wo: str, target_num: int) -> bool:
    """True if from_wo already (transitively) depends on target_num."""
    stack = list(edges.get(from_wo, []) or [])
    seen: set[int] = set()
    while stack:
        n = int(stack.pop())
        if n in seen:
            continue
        seen.add(n)
        if n == target_num:
            return True
        stack.extend(int(x) for x in (edges.get(wo_id_for(n), []) or []))
    return False


def would_cycle(edges: dict[str, list[int]], later_wo: str, earlier_num: int) -> bool:
    """Adding later_wo → earlier_num cycles if earlier already depends on later."""
    later_num = wo_num(later_wo)
    if later_num is None:
        return True
    if later_num == earlier_num:
        return True
    return depends_reaches(edges, wo_id_for(earlier_num), later_num)


def propose_deterministic_edges(
    open_wos: list[dict],
    advisor_edges: dict[str, list[int]] | None = None,
    *,
    max_edges: int = 20,
) -> list[dict]:
    """Propose later→earlier edges for open WOs that share a service or file."""
    advisor_edges = {k: list(v) for k, v in (advisor_edges or {}).items()}
    graph = graph_from(open_wos, advisor_edges)
    proposed: list[dict] = []
    wos = [w for w in open_wos if wo_num(w.get("wo") or w.get("number")) is not None]
    for i, a in enumerate(wos):
        for b in wos[i + 1:]:
            if len(proposed) >= max_edges:
                return proposed
            reason = overlap_reason(a, b)
            if not reason:
                continue
            earlier, later = order_pair(a, b)
            later_id = later.get("wo") or wo_id_for(int(later["number"]))
            earlier_num = int(earlier["number"])
            if earlier_num in existing_depends(later, graph):
                continue
            if would_cycle(graph, later_id, earlier_num):
                continue
            graph.setdefault(later_id, []).append(earlier_num)
            proposed.append({
                "later": later_id,
                "earlier": earlier_num,
                "reason": reason,
                "source": "deterministic",
                "confidence": "high",
            })
    return proposed


def parse_llm_edges(text: str, allowed_nums: set[int]) -> list[dict]:
    """Parse LLM JSON; drop anything that isn't a high-confidence allowed pair."""
    raw = (text or "").strip()
    raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw.strip())
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    edges_in = data.get("edges") if isinstance(data, dict) else None
    if not isinstance(edges_in, list):
        return []
    out: list[dict] = []
    for item in edges_in:
        if not isinstance(item, dict):
            continue
        if str(item.get("confidence") or "").lower() != "high":
            continue
        later_n = wo_num(item.get("later") or "")
        earlier_n = wo_num(item.get("earlier") or "")
        if later_n is None or earlier_n is None:
            continue
        if later_n not in allowed_nums or earlier_n not in allowed_nums:
            continue
        if later_n == earlier_n:
            continue
        reason = str(item.get("reason") or "LLM-suggested sequencing").strip()[:240]
        out.append({
            "later": wo_id_for(later_n),
            "earlier": earlier_n,
            "reason": reason,
            "source": "llm",
            "confidence": "high",
        })
    return out[:10]


def compact_wo_for_llm(wo: dict) -> dict:
    return {
        "wo": wo.get("wo") or wo_id_for(int(wo["number"])),
        "title": (wo.get("title") or "")[:80],
        "priority": wo.get("priority", "P2"),
        "services": sorted(service_set_from_spec(wo)),
        "files": list(wo.get("files_likely_changed") or [])[:8],
        "depends_on": [int(x) if not isinstance(x, int) else x
                       for x in (wo.get("depends_on") or []) if wo_num(x) is not None],
    }


async def llm_extra_edges(
    anthropic_key: str,
    open_wos: list[dict],
    *,
    max_wos: int = 15,
) -> list[dict]:
    if not anthropic_key or not open_wos:
        return []
    ranked = sorted(
        open_wos,
        key=lambda w: (_priority_key(w.get("priority", "P2")), int(w["number"])),
    )[:max_wos]
    allowed = {int(w["number"]) for w in ranked}
    payload = [compact_wo_for_llm(w) for w in ranked]
    system = (
        "You are the conflict advisor for an AI software factory. "
        "WOs dispatch in priority order unless depends_on says otherwise. "
        "Propose extra depends_on edges so two WOs that would collide "
        "(same service, same files, or an obvious sequential dependency) "
        "do not run in the wrong order. "
        "Reply ONLY with JSON:\n"
        '{"edges":[{"later":"WO-NNN","earlier":"WO-MMM","reason":"short","confidence":"high"}]}\n'
        "Rules: later must wait for earlier. Only confidence=high edges. "
        "Do not invent WO numbers. Empty edges is fine. Max 8 edges."
    )
    user = "Open work orders:\n" + json.dumps(payload, indent=2)
    try:
        import anthropic
        from llm_client import messages_create

        client = anthropic.Anthropic(api_key=anthropic_key)
        model = os.getenv("CONFLICT_ADVISOR_MODEL", "claude-haiku-4-5-20251001")
        msg = await messages_create(
            client,
            model=model,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = next(b.text for b in msg.content if b.type == "text").strip()
        return parse_llm_edges(text, allowed)
    except Exception:
        return []


def merge_edges(
    deterministic: list[dict],
    llm: list[dict],
    advisor_edges: dict[str, list[int]],
    open_by_id: dict[str, dict],
) -> list[dict]:
    """Dedupe, refuse cycles, refuse unknown WOs. Deterministic wins on conflict."""
    working = graph_from(list(open_by_id.values()), advisor_edges)
    accepted: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for edge in deterministic + llm:
        later = edge["later"]
        earlier = int(edge["earlier"])
        key = (later, earlier)
        if key in seen:
            continue
        if later not in open_by_id or wo_id_for(earlier) not in open_by_id:
            continue
        later_wo = open_by_id[later]
        if earlier in existing_depends(later_wo, working):
            continue
        if would_cycle(working, later, earlier):
            continue
        working.setdefault(later, []).append(earlier)
        seen.add(key)
        accepted.append(edge)
    return accepted


async def run_advisor_pass(
    open_wos: list[dict],
    advisor_edges: dict[str, list[int]],
    anthropic_key: str = "",
    apply_edge: Callable[[str, int, str], Any] | None = None,
) -> dict:
    """Propose and optionally persist edges. Returns a summary for intelligence status."""
    open_by_id = {}
    for w in open_wos:
        n = wo_num(w.get("wo") or w.get("number"))
        if n is None:
            continue
        w = {**w, "number": n, "wo": w.get("wo") or wo_id_for(n)}
        open_by_id[w["wo"]] = w
    normalized = list(open_by_id.values())

    deterministic = propose_deterministic_edges(normalized, advisor_edges)
    llm = await llm_extra_edges(anthropic_key, normalized)
    accepted = merge_edges(deterministic, llm, advisor_edges, open_by_id)

    actions: list[str] = []
    for edge in accepted:
        reason = f"{edge['source']}: {edge['reason']}"
        if apply_edge:
            apply_edge(edge["later"], int(edge["earlier"]), reason)
        actions.append(
            f"Advisor: {edge['later']} waits for WO-{edge['earlier']} ({edge['reason']})"
        )

    return {
        "edges_added": len(accepted),
        "deterministic": sum(1 for e in accepted if e.get("source") == "deterministic"),
        "llm": sum(1 for e in accepted if e.get("source") == "llm"),
        "actions": actions,
        "open_wos_considered": len(normalized),
    }
