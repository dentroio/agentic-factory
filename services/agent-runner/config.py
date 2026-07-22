import os
import socket

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://orchestrator:8100")
LOCAL_REPO_PATH = os.getenv("LOCAL_REPO_PATH", "")  # absolute path to local project clone on host
PREFERRED_AGENT = os.getenv("PREFERRED_AGENT", "claude")   # claude | cursor | codex | gemini
AGENT_NAME = os.getenv("AGENT_NAME", "claude-runner")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))
CURSOR_API_KEY = os.getenv("CURSOR_API_KEY", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
WORKTREE_BASE = os.getenv("WORKTREE_BASE", "/workspace")
HOSTNAME = socket.gethostname()
API_SECRET = os.getenv("API_SECRET", "")

# Maximum seconds to wait for a single agent run before giving up
AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT", str(60 * 120)))  # 2 hours

# Domain filter: runner only claims WOs whose services field matches.
# Empty string (default) means no filter — claim any WO.
# Example: "frontend" or "data-service,src"
DOMAIN_FILTER = os.getenv("DOMAIN_FILTER", "")
