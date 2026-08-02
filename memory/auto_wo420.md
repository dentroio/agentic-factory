---
name: status-site-dispatch-active-counts
description: Dashboard pages must use the shared _dispatch_status_counts() helper for "active WO" counts instead of reimplementing status filters
metadata:
  type: project
---

In services/status-site/main.py, dispatch WO status has more states than "in_progress" vs "complete": claimed, in_progress, awaiting_human, awaiting_commit, stale, rejected, retry_queued, queued/pending/waiting. Before this PR, each dashboard page (Overview, Factory, PM) independently reimplemented its own filter over these states to answer "how many WOs are active," and they silently disagreed (Overview only counted in_progress; Factory counted everything != complete). This caused real incidents (stuck/stale WOs) to be invisible on some pages but visible on others.

**Why:** The dispatch status set is not a simple binary; any new "active count" added ad-hoc will likely diverge from existing coun