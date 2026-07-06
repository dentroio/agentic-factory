"""
Lightweight HTTP draft server — exposes POST /api/draft for WO spec generation.

Runs as a background thread inside the agent-runner process. The orchestrator
proxies here when the user selects a CLI backend (claude/cursor/codex/gemini)
instead of the Claude API key path.

No extra dependencies — uses Python stdlib http.server only.
"""
import asyncio
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

DRAFT_PORT = int(os.getenv("DRAFT_PORT", "8101"))

_PROMPT_TEMPLATE = """\
You are a software engineering planning agent. Convert this plain-English feature request \
into a structured Work Order spec.

Return ONLY valid JSON (no markdown fences, no preamble) with these exact keys:
- title: short action-oriented title (max 60 chars)
- priority: "P1", "P2", or "P3"
- effort: "XS", "S", "M", "L", or "XL"
- services: comma-separated service names affected (e.g. "orchestrator, status-site")
- problem: 2-4 sentences describing the pain point
- what_to_build: technical description with specific files and approach
- acceptance_criteria: array of 3-6 verifiable checklist items
- notes: any constraints or context (empty string if none)

Risk tiers: P1=core/schema changes (human merge required), P2=additive features/UI \
(auto-merge allowed), P3=docs only (direct to main).
Effort: XS<1h | S~2h | M=half day | L=full day | XL=2-3 days

WO number: {num:03d}

Request:
{description}"""


def _probe_backends() -> dict[str, bool]:
    """Check which agent CLIs are installed and executable."""
    import shutil

    def _exe(*paths) -> bool:
        for p in paths:
            if p and os.path.isfile(p) and os.access(p, os.X_OK):
                return True
        return False

    # Claude Code installs its CLI inside a versioned app bundle — scan for it
    claude_bundle = None
    claude_code_dir = os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code"
    )
    if os.path.isdir(claude_code_dir):
        try:
            for version_dir in sorted(os.listdir(claude_code_dir), reverse=True):
                candidate = os.path.join(
                    claude_code_dir, version_dir,
                    "claude.app", "Contents", "MacOS", "claude",
                )
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    claude_bundle = candidate
                    break
        except OSError:
            pass

    return {
        "claude": _exe(
            shutil.which("claude"),
            os.path.expanduser("~/.local/bin/claude"),
            claude_bundle,
        ),
        "cursor": _exe(
            shutil.which("agent"),
            os.path.expanduser("~/.local/bin/agent"),
            os.path.expanduser("~/.local/bin/cursor-agent"),
        ),
        "codex": _exe(shutil.which("codex")),
        "gemini": _exe(shutil.which("gemini")),
    }


class _ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class _DraftHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            try:
                import backends.quota_state as _qs
                exhausted = _qs.exhausted_backends()
            except Exception:
                exhausted = []
            self._json(200, {"status": "ok", "port": DRAFT_PORT, "backends": _probe_backends(), "exhausted_backends": exhausted})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/chat":
            self._handle_chat()
            return
        if self.path != "/api/draft":
            self._json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"error": "invalid JSON body"})
            return

        description = str(body.get("description", "")).strip()
        next_wo_num = int(body.get("next_wo_num", 1))
        backend_name = body.get("backend") or None

        if not description:
            self._json(400, {"error": "description is required"})
            return

        try:
            from backends import get_backend
            backend = get_backend(backend_name)
            prompt = _PROMPT_TEMPLATE.format(num=next_wo_num, description=description)
            text = asyncio.run(backend.ask(prompt))

            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text)

            data = json.loads(text)
            self._json(200, data)
        except json.JSONDecodeError:
            raw = text[:400] if "text" in dir() else "(no output)"
            self._json(500, {"error": "LLM returned invalid JSON", "raw": raw})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _handle_chat(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"error": "invalid JSON body"})
            return

        system = str(body.get("system", "")).strip()
        message = str(body.get("message", "")).strip()
        history = body.get("history", [])
        backend_name = body.get("backend") or None

        if not message:
            self._json(400, {"error": "message is required"})
            return

        # Build a single prompt: system + history + user message
        parts: list[str] = []
        if system:
            parts.append(system)
        for h in history:
            role = str(h.get("role", "user")).upper()
            content = str(h.get("content", ""))
            parts.append(f"[{role}]: {content}")
        parts.append(f"[USER]: {message}")
        parts.append("[ASSISTANT]:")
        full_prompt = "\n\n".join(parts)

        try:
            from backends import get_backend
            backend = get_backend(backend_name)
            reply = asyncio.run(backend.ask(full_prompt))
            self._json(200, {"reply": reply})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def _json(self, code: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[draft-server] {fmt % args}", flush=True)


def start() -> None:
    server = _ThreadedServer(("0.0.0.0", DRAFT_PORT), _DraftHandler)
    print(f"[draft-server] Listening on :{DRAFT_PORT}", flush=True)
    server.serve_forever()
