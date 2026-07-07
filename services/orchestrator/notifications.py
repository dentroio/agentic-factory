"""Notification dispatch — ntfy.sh and Slack webhooks for human-in-the-loop alerts."""
import os
from urllib.parse import quote

import httpx

# Env-var defaults (overridden by secrets store values passed at call time)
_ENV_NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
_ENV_NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


def _ntfy_topic(secrets: dict | None = None) -> str:
    return (secrets or {}).get("NTFY_TOPIC") or _ENV_NTFY_TOPIC


def _ntfy_server(secrets: dict | None = None) -> str:
    return (secrets or {}).get("NTFY_SERVER") or _ENV_NTFY_SERVER or "https://ntfy.sh"


def _slack_url(secrets: dict | None = None) -> str:
    return (secrets or {}).get("SLACK_WEBHOOK_URL") or SLACK_WEBHOOK_URL


async def _send_ntfy(
    title: str,
    body: str,
    priority: str = "high",
    tags: str = "robot,eyes",
    secrets: dict | None = None,
) -> None:
    topic = _ntfy_topic(secrets)
    if not topic:
        return
    url = f"{_ntfy_server(secrets)}/{topic}"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(url, content=body.encode("utf-8"), headers={
                "Title": quote(title),   # URL-encode for non-ASCII chars (emoji, etc.)
                "Priority": priority,
                "Tags": tags,
                "Content-Type": "text/plain; charset=utf-8",
            })
    except Exception as e:
        print(f"[notifications] ntfy failed: {e}")


async def _send_slack(text: str, blocks: list | None = None, secrets: dict | None = None) -> None:
    url = _slack_url(secrets)
    if not url:
        return
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(url, json=payload)
    except Exception as e:
        print(f"[notifications] slack failed: {e}")


async def notify_validation_needed(
    wo_id: str,
    agent: str,
    title: str = "",
    verify_url: str = "",
    thread_summary: str = "",
    secrets: dict | None = None,
) -> None:
    """Alert when a WO reaches the human review queue."""
    display = f"{wo_id}{': ' + title if title else ''}"
    body_lines = [f"Agent {agent} completed {wo_id} and needs your sign-off."]
    if thread_summary:
        body_lines.append(thread_summary)
    if verify_url:
        body_lines.append(verify_url)
    await _send_ntfy(
        title=f"👀 Review needed: {wo_id}",
        body="\n".join(body_lines),
        priority="high",
        tags="robot,eyes",
        secrets=secrets,
    )
    blocks = [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": (
            f":robot_face: *{wo_id} is ready for review*\n"
            f"Agent *{agent}* completed `{display}` and passed the quality gate.\n"
            + (f"_{thread_summary}_\n" if thread_summary else "")
            + (f"<{verify_url}|Open in factory →>" if verify_url else "")
        )},
    }]
    await _send_slack(
        f":robot_face: *Review needed:* `{wo_id}` — {agent} completed work and awaits sign-off.",
        blocks,
        secrets=secrets,
    )


async def notify_wo_complete(
    wo_id: str,
    agent: str,
    pr_url: str = "",
    secrets: dict | None = None,
) -> None:
    """Alert when a WO PR is merged and the work order is done."""
    await _send_ntfy(
        title=f"✅ {wo_id} merged",
        body=f"Agent {agent} completed {wo_id}." + (f"\n{pr_url}" if pr_url else ""),
        priority="default",
        tags="white_check_mark",
        secrets=secrets,
    )
    await _send_slack(
        f":white_check_mark: *{wo_id} complete* — merged by `{agent}`" + (f" — <{pr_url}|PR>" if pr_url else ""),
        secrets=secrets,
    )


async def notify_wo_error(
    wo_id: str,
    agent: str,
    reason: str = "",
    secrets: dict | None = None,
) -> None:
    """Alert when an agent fails or gives up on a WO."""
    await _send_ntfy(
        title=f"⚠️ {wo_id} stalled",
        body=f"Agent {agent} could not complete {wo_id}." + (f"\n{reason[:200]}" if reason else ""),
        priority="high",
        tags="warning",
        secrets=secrets,
    )
    await _send_slack(
        f":warning: *{wo_id} stalled* — `{agent}` gave up." + (f"\n_{reason[:200]}_" if reason else ""),
        secrets=secrets,
    )


async def notify_dependabot(
    action: str,
    pr_numbers: list[int],
    details: str = "",
    secrets: dict | None = None,
) -> None:
    """Alert for Dependabot PR events (conflicts detected, PRs merged)."""
    prs = ", ".join(f"#{n}" for n in pr_numbers)
    if action == "conflict":
        await _send_ntfy(
            title=f"🔀 Dependabot conflict — {prs}",
            body=f"Merge conflict detected on {prs}. Rebase triggered automatically.",
            priority="low",
            tags="arrows_counterclockwise",
            secrets=secrets,
        )
        await _send_slack(
            f":arrows_counterclockwise: *Dependabot conflict* on {prs} — rebase triggered automatically.",
            secrets=secrets,
        )
    elif action == "merged":
        await _send_ntfy(
            title=f"📦 Dependabot merged — {prs}",
            body=details or f"Dependency PR {prs} merged successfully.",
            priority="low",
            tags="package",
            secrets=secrets,
        )
        await _send_slack(
            f":package: *Dependabot merged* {prs}" + (f" — {details}" if details else ""),
            secrets=secrets,
        )


async def notify_test(secrets: dict | None = None) -> bool:
    """Send a test notification. Returns True if ntfy or Slack is configured."""
    topic = _ntfy_topic(secrets)
    slack = _slack_url(secrets)
    if not topic and not slack:
        return False
    if topic:
        await _send_ntfy(
            title="🏭 Factory notifications active",
            body="Your AI Factory will send alerts here for WO completions, reviews, and errors.",
            priority="default",
            tags="bell",
            secrets=secrets,
        )
    if slack:
        await _send_slack(
            ":factory: *Factory notifications active* — WO completions, reviews, and errors will appear here.",
            secrets=secrets,
        )
    return True
