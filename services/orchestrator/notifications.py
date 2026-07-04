"""Notification dispatch — ntfy.sh and Slack webhooks for human-in-the-loop alerts."""
import os

import httpx

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


async def _send_ntfy(title: str, body: str, priority: str = "high", tags: str = "robot,eyes") -> None:
    if not NTFY_TOPIC:
        return
    url = f"{NTFY_SERVER}/{NTFY_TOPIC}"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(url, content=body.encode(), headers={
                "Title": title,
                "Priority": priority,
                "Tags": tags,
            })
    except Exception as e:
        print(f"[notifications] ntfy failed: {e}")


async def _send_slack(text: str, blocks: list | None = None) -> None:
    if not SLACK_WEBHOOK_URL:
        return
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(SLACK_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"[notifications] slack failed: {e}")


async def notify_validation_needed(
    wo_id: str,
    agent: str,
    title: str = "",
    verify_url: str = "",
    thread_summary: str = "",
) -> None:
    """Fire-and-forget alerts when a WO reaches the human review queue."""
    display = f"{wo_id}{': ' + title if title else ''}"

    # ntfy.sh
    body_lines = [f"Agent {agent} completed {wo_id} and needs your sign-off."]
    if thread_summary:
        body_lines.append(thread_summary)
    if verify_url:
        body_lines.append(verify_url)
    await _send_ntfy(
        title=f"Review needed: {wo_id}",
        body="\n".join(body_lines),
        priority="high",
        tags="robot,eyes",
    )

    # Slack
    slack_text = f":robot_face: *Review needed:* `{wo_id}` — {agent} completed work and awaits sign-off."
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":robot_face: *{wo_id} is ready for review*\n"
                    f"Agent *{agent}* completed `{display}` and passed the quality gate.\n"
                    + (f"_{thread_summary}_\n" if thread_summary else "")
                    + (f"<{verify_url}|Open in factory →>" if verify_url else "")
                ),
            },
        }
    ]
    await _send_slack(slack_text, blocks)
