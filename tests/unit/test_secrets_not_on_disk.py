"""AF-12: factory secrets must not land in the repo, stdout, or world-readable plists."""
from __future__ import annotations

import os
import plistlib
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNNER_DIR = REPO_ROOT / "services" / "agent-runner"
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(AGENT_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNNER_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import draft_server as ds  # noqa: E402
import publish_to_gdrive as gdrive  # noqa: E402


def test_makefile_and_setup_do_not_write_env_runtime():
    makefile = (REPO_ROOT / "Makefile").read_text()
    setup = (SCRIPTS_DIR / "agent-setup.sh").read_text()
    assert ".env.runtime" not in makefile
    assert ".env.runtime" not in setup
    assert "scripts/compose-with-env.sh" in makefile
    assert "scripts/compose-with-env.sh" in setup


def test_compose_helper_creates_0600_tempfile_and_deletes_it(tmp_path):
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    stub_env = stub_dir / "factory-env.sh"
    stub_env.write_text("#!/bin/bash\necho SECRET_KEY=supersecret\n", encoding="utf-8")
    stub_env.chmod(0o755)

    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    observed = tmp_path / "observed"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        f'obs="{observed}"\n'
        "mkdir -p \"$obs\"\n"
        "env_file=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--env-file\" ]; then\n"
        "    env_file=\"$2\"\n"
        "    shift 2\n"
        "    continue\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "if [ -z \"$env_file\" ]; then\n"
        "  echo missing-env-file > \"$obs/error\"\n"
        "  exit 1\n"
        "fi\n"
        "stat -f '%Lp' \"$env_file\" > \"$obs/mode\" 2>/dev/null "
        "|| stat -c '%a' \"$env_file\" > \"$obs/mode\"\n"
        "echo \"$env_file\" > \"$obs/path\"\n"
        "grep -q '^SECRET_KEY=supersecret$' \"$env_file\" || exit 1\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["TMPDIR"] = str(tmpdir)
    env["FACTORY_ENV_SCRIPT"] = str(stub_env)
    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "compose-with-env.sh"), "up", "-d"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (observed / "mode").read_text().strip() == "600"
    leftover = list(tmpdir.glob("factory-env.*"))
    assert leftover == []
    env_path = Path((observed / "path").read_text().strip())
    assert not env_path.exists()


def test_publish_to_gdrive_does_not_print_secret_values():
    text = (SCRIPTS_DIR / "publish_to_gdrive.py").read_text()
    assert "creds.refresh_token}" not in text
    assert "GDRIVE_CLIENT_SECRET  =  {client_secret}" not in text
    assert "write_gdrive_oauth_env" in text


def test_gdrive_oauth_env_is_mode_0600_and_not_printed(tmp_path, capsys):
    dest = tmp_path / "gdrive-oauth.env"
    refresh = "1//secret-refresh-token"
    secret = "gdrive-client-secret-value"
    written = gdrive.write_gdrive_oauth_env(
        refresh_token=refresh,
        client_id="client-id",
        client_secret=secret,
        dest=dest,
    )
    assert written == dest
    mode = stat.S_IMODE(dest.stat().st_mode)
    assert mode == 0o600
    captured = capsys.readouterr()
    assert refresh not in captured.out
    assert secret not in captured.out
    assert dest.read_text(encoding="utf-8").splitlines()[0] == f"GDRIVE_REFRESH_TOKEN={refresh}"


def test_write_secure_plist_is_mode_0600(tmp_path):
    meta = dict(ds._AGENT_META["claude"])
    path = tmp_path / "com.dentroio.test.plist"
    ds.write_secure_plist(str(path), ds._plist_dict("claude", meta))
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_plist_values_with_lt_and_amp_round_trip(tmp_path):
    meta = dict(ds._AGENT_META["claude"])
    meta["extra_env"] = {
        "ANTHROPIC_API_KEY": "sk-foo<&bar>",
        "NOTE": "a & b < c",
    }
    path = tmp_path / "agent.plist"
    ds.write_secure_plist(str(path), ds._plist_dict("claude", meta))
    xml = path.read_text(encoding="utf-8")
    assert "<&" not in xml
    assert "&lt;" in xml
    assert "&amp;" in xml
    with path.open("rb") as handle:
        loaded = plistlib.load(handle)
    env = loaded["EnvironmentVariables"]
    assert env["ANTHROPIC_API_KEY"] == "sk-foo<&bar>"
    assert env["NOTE"] == "a & b < c"


def test_draft_server_creates_plists_via_write_secure_plist():
    text = (AGENT_RUNNER_DIR / "draft_server.py").read_text()
    assert "f.write(_plist_content" not in text
    assert "write_secure_plist(plist_path" in text


def test_agent_install_chmods_plists_600():
    text = (SCRIPTS_DIR / "agent-install.sh").read_text()
    assert "chmod 600 \"$PLIST_DEST\"" in text
    assert "chmod 600 \"$domain_plist\"" in text
