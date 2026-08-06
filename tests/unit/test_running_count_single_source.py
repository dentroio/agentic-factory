"""Guards the one definition of "Running" against a fourth re-implementation.

The Overview showed 3, the PM board showed 5 and the Factory showed 5, over
identical dispatch data, because four places each decided for themselves what
running meant: two board columns derived from GitHub branches, a status bar
that counted every dispatch entry that wasn't complete, and a snippet of
JavaScript that filtered `in_progress` and forgot `claimed` — then overwrote
the correct server-rendered number a second after the page loaded.

test_wo_reconcile.py pins the behaviour of the shared helpers. This pins the
wiring: main.py must reach the number through dispatch_status_counts(), and no
template may count dispatch statuses in the browser. A behavioural test cannot
catch a new page that quietly grows its own filter, which is exactly how this
diverged the first time.

main.py and the templates can't be imported here (FastAPI and Jinja aren't
installed in CI), so this reads their source.
"""

from __future__ import annotations

import re
from pathlib import Path

STATUS_SITE = Path(__file__).resolve().parents[2] / "services" / "status-site"
MAIN_PY = STATUS_SITE / "main.py"
TEMPLATES = STATUS_SITE / "templates"

# Every dispatch status that means "an agent holds this WO". Mirrored from
# wo_reconcile so a template can be caught hard-coding one of them.
RUNNING_STATUSES = ("claimed", "in_progress")


def test_main_defines_no_dispatch_status_sets_of_its_own():
    """The sets live in wo_reconcile.py. main.py had its own copies, which is
    how the Factory page and the Overview drifted apart while both looked
    correct in review."""
    src = MAIN_PY.read_text()
    assert "_IN_PROGRESS_STATUSES" not in src
    assert "_AWAITING_REVIEW_STATUSES" not in src
    assert "_NEEDS_ATTENTION_STATUSES" not in src
    assert "def _dispatch_status_counts" not in src


def test_every_running_assignment_in_main_uses_the_shared_helper():
    """`dispatch_running` is rendered by the Overview and by the PM View, and
    both must resolve to dispatch_status_counts(...)["in_progress"] — not to a
    board column, not to a hand-rolled comprehension over dispatch."""
    src = MAIN_PY.read_text()
    assignments = re.findall(r"^\s*dispatch_running\s*=\s*(.+)$", src, re.MULTILINE)

    assert len(assignments) == 2, f"expected one per page, found {assignments}"
    for expr in assignments:
        assert "dispatch_counts[" in expr or "dispatch_status_counts(" in expr, expr
        assert '"in_progress"' in expr, expr


def test_the_factory_page_reads_the_same_helper():
    src = MAIN_PY.read_text()
    assert re.search(r"active_breakdown\s*=\s*dispatch_status_counts\(", src)


def test_no_template_filters_the_dispatch_payload_for_running():
    """The Overview's JS did `data.filter(w => w.status === 'in_progress')` on
    the raw dispatch payload and assigned the result to the Running stat.
    Templates consume /api/factory/counts instead.

    Comparing a single row's own status to colour its badge is fine — that
    labels one entry rather than defining how many are running — so this looks
    specifically for a running status inside a filter over the collection.
    """
    pattern = re.compile(
        rf"(filter|reduce)\s*\([^;]*?\b(?:{'|'.join(RUNNING_STATUSES)})\b",
        re.DOTALL,
    )
    offenders = []
    for template in sorted(TEMPLATES.glob("*.html")):
        src = template.read_text()
        for m in pattern.finditer(src):
            offenders.append(f"{template.name}:{src[: m.start()].count(chr(10)) + 1}")

    assert offenders == [], f"template(s) re-deriving the running filter: {offenders}"


def test_the_counts_endpoint_the_templates_fetch_exists():
    src = MAIN_PY.read_text()
    assert '@app.get("/api/factory/counts")' in src

    fetched = set()
    for template in TEMPLATES.glob("*.html"):
        if "/api/factory/counts" in template.read_text():
            fetched.add(template.name)
    assert {"dashboard.html", "factory.html"} <= fetched
