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
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

# Wake event + pending dispatch — set by POST /dispatch, consumed by runner.py
_wake_event = threading.Event()
_dispatch_lock = threading.Lock()
_pending_dispatch: dict | None = None


def pop_dispatch() -> dict | None:
    """Return and clear any pending PM dispatch. Thread-safe."""
    global _pending_dispatch
    with _dispatch_lock:
        item = _pending_dispatch
        _pending_dispatch = None
    if item:
        _wake_event.clear()
    return item

DRAFT_PORT = int(os.getenv("DRAFT_PORT", "8101"))

_PLIST_DIR = os.path.expanduser("~/Library/LaunchAgents")
_PLIST_LOG_DIR = os.path.expanduser("~/Library/Logs/factory-agent")
_RUNNER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run-local.sh")
_RUNNER_DIR_PATH = os.path.dirname(os.path.abspath(__file__))

_AGENT_META: dict[str, dict] = {
    "claude": {
        "auth_type": "both",
        "api_key_env": "ANTHROPIC_API_KEY",
        "preferred_agent": "claude",
        "agent_name": "claude-runner",
        "label": "com.dentroio.factory-agent-claude",
        "log_suffix": "claude",
        "extra_env": {"DRAFT_PORT": "8102"},
    },
    "cursor": {
        "auth_type": "subscription",
        "api_key_env": None,
        "preferred_agent": "cursor",
        "agent_name": "cursor-runner",
        "label": "com.dentroio.factory-agent-cursor",
        "log_suffix": "cursor",
        "extra_env": {},
    },
    "codex": {
        "auth_type": "both",
        "api_key_env": "OPENAI_API_KEY",
        "preferred_agent": "codex",
        "agent_name": "codex-runner",
        "label": "com.dentroio.factory-agent-codex",
        "log_suffix": "codex",
        "extra_env": {},
    },
    "gemini": {
        "auth_type": "subscription",
        "api_key_env": None,
        "preferred_agent": "gemini",
        "agent_name": "gemini-runner",
        "label": "com.dentroio.factory-agent-gemini",
        "log_suffix": "gemini",
        "extra_env": {},
    },
}


def _plist_content(name: str, meta: dict) -> str:
    label = meta["label"]
    log_suffix = meta["log_suffix"]
    extra_keys = "".join(
        f"\n        <key>{k}</key>\n        <string>{v}</string>"
        for k, v in meta.get("extra_env", {}).items()
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{_RUNNER_SCRIPT}</string>
    </array>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PREFERRED_AGENT</key>
        <string>{meta["preferred_agent"]}</string>
        <key>AGENT_NAME</key>
        <string>{meta["agent_name"]}</string>{extra_keys}
    </dict>

    <key>WorkingDirectory</key>
    <string>{_RUNNER_DIR_PATH}</string>

    <key>KeepAlive</key>
    <true/>

    <key>RunAtLoad</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>StandardOutPath</key>
    <string>{_PLIST_LOG_DIR}/out-{log_suffix}.log</string>

    <key>StandardErrorPath</key>
    <string>{_PLIST_LOG_DIR}/err-{log_suffix}.log</string>

    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>"""

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
        elif self.path == "/api/agents":
            self._get_agents_status()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/dispatch":
            self._handle_dispatch()
            return
        if self.path == "/api/chat":
            self._handle_chat()
            return
        if self.path.startswith("/api/agents/"):
            parts = self.path.split("/")
            if len(parts) == 5 and parts[4] in ("start", "stop"):
                name, action = parts[3], parts[4]
                if action == "start":
                    self._handle_agents_start(name)
                else:
                    self._handle_agents_stop(name)
            else:
                self._json(404, {"error": "not found"})
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

    def _handle_dispatch(self) -> None:
        global _pending_dispatch
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._json(400, {"error": "invalid JSON body"})
            return
        wo = str(body.get("wo", "")).strip()
        backend = str(body.get("backend", "claude")).strip()
        if not wo:
            self._json(400, {"error": "wo is required"})
            return
        with _dispatch_lock:
            _pending_dispatch = {"wo": wo, "backend": backend}
        _wake_event.set()
        print(f"[draft-server] dispatch wake: {wo} → {backend}", flush=True)
        self._json(200, {"ok": True, "wo": wo, "backend": backend})

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

    def _get_agents_status(self) -> None:
        clis = _probe_backends()
        try:
            result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5)
            launchctl_out = result.stdout
        except Exception:
            launchctl_out = ""

        agents: dict[str, dict] = {}
        for name, meta in _AGENT_META.items():
            label = meta["label"]
            plist_path = os.path.join(_PLIST_DIR, f"{label}.plist")
            daemon_pid: int | None = None
            daemon_loaded = False
            for line in launchctl_out.splitlines():
                parts = line.split("\t")
                if len(parts) == 3 and parts[2] == label:
                    daemon_loaded = True
                    try:
                        daemon_pid = int(parts[0]) if parts[0] != "-" else None
                    except (ValueError, IndexError):
                        daemon_pid = None
                    break
            api_key_set = None
            if meta["api_key_env"]:
                api_key_set = bool(os.getenv(meta["api_key_env"]))
            agents[name] = {
                "auth_type": meta["auth_type"],
                "api_key_env": meta["api_key_env"],
                "cli_detected": clis.get(name, False),
                "api_key_set": api_key_set,
                "plist_exists": os.path.isfile(plist_path),
                "daemon_loaded": daemon_loaded,
                "daemon_pid": daemon_pid,
            }
        self._json(200, {"agents": agents})

    def _handle_agents_start(self, name: str) -> None:
        meta = _AGENT_META.get(name)
        if not meta:
            self._json(404, {"error": f"Unknown agent: {name}"})
            return
        plist_path = os.path.join(_PLIST_DIR, f"{meta['label']}.plist")
        if not os.path.isfile(plist_path):
            try:
                os.makedirs(_PLIST_LOG_DIR, exist_ok=True)
                with open(plist_path, "w") as f:
                    f.write(_plist_content(name, meta))
            except Exception as e:
                self._json(500, {"error": f"Failed to create plist: {e}"})
                return
        uid = os.getuid()
        try:
            r = subprocess.run(
                ["launchctl", "bootstrap", f"gui/{uid}", plist_path],
                capture_output=True, text=True, timeout=10,
            )
            combined = (r.stdout + r.stderr).lower()
            if r.returncode != 0 and "already bootstrapped" not in combined:
                self._json(500, {"error": r.stderr.strip() or "launchctl bootstrap failed"})
                return
        except Exception as e:
            self._json(500, {"error": str(e)})
            return
        print(f"[draft-server] agent start: {name}", flush=True)
        self._json(200, {"ok": True, "agent": name, "action": "start"})

    def _handle_agents_stop(self, name: str) -> None:
        meta = _AGENT_META.get(name)
        if not meta:
            self._json(404, {"error": f"Unknown agent: {name}"})
            return
        uid = os.getuid()
        try:
            r = subprocess.run(
                ["launchctl", "bootout", f"gui/{uid}/{meta['label']}"],
                capture_output=True, text=True, timeout=10,
            )
            combined = (r.stdout + r.stderr).lower()
            if r.returncode != 0 and "no such process" not in combined and "not bootstrapped" not in combined:
                self._json(500, {"error": r.stderr.strip() or "launchctl bootout failed"})
                return
        except Exception as e:
            self._json(500, {"error": str(e)})
            return
        print(f"[draft-server] agent stop: {name}", flush=True)
        self._json(200, {"ok": True, "agent": name, "action": "stop"})

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
