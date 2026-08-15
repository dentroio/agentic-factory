"""AF-10: orchestrator uses a scoped Vault token; root token stays offline."""
from __future__ import annotations

import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCH_DIR = REPO_ROOT / "services" / "orchestrator"
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(ORCH_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import vault_auth  # noqa: E402
import keychain_set as ks  # noqa: E402


def _service_block(text: str, name: str) -> str:
    padded = "\n" + text
    marker = f"\n  {name}:\n"
    start = padded.index(marker) + 1
    lines = padded[start:].splitlines()
    kept = [lines[0]]
    for line in lines[1:]:
        if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
            break
        if line and not line.startswith(" "):
            break
        kept.append(line)
    return "\n".join(kept)


def test_load_vault_token_prefers_env(tmp_path):
    (tmp_path / vault_auth.ORCHESTRATOR_TOKEN_FILENAME).write_text("from-file", encoding="utf-8")
    got = vault_auth.load_vault_token(tmp_path, env={"VAULT_TOKEN": "from-env"})
    assert got == "from-env"


def test_load_vault_token_reads_orchestrator_file(tmp_path):
    (tmp_path / vault_auth.ORCHESTRATOR_TOKEN_FILENAME).write_text("scoped-from-file\n", encoding="utf-8")
    (tmp_path / vault_auth.ROOT_TOKEN_FILENAME).write_text("hvs.root-must-be-ignored", encoding="utf-8")
    got = vault_auth.load_vault_token(tmp_path, env={})
    assert got == "scoped-from-file"
    assert "root" not in got


def test_load_vault_token_ignores_root_token_file(tmp_path):
    (tmp_path / vault_auth.ROOT_TOKEN_FILENAME).write_text("hvs.root-only", encoding="utf-8")
    got = vault_auth.load_vault_token(tmp_path, env={})
    assert got == ""


def test_orchestrator_source_does_not_read_root_token():
    text = (ORCH_DIR / "orchestrator.py").read_text(encoding="utf-8")
    assert "root_token" not in text
    assert "load_vault_token" in text


def test_compose_orchestrator_mounts_orch_token_not_keys():
    text = (REPO_ROOT / "docker-compose.status.yml").read_text(encoding="utf-8")
    orch = _service_block(text, "orchestrator")
    vault = _service_block(text, "vault")
    assert "vault-orch-token:/vault/keys:ro" in orch
    assert "vault-keys:" not in orch
    assert "vault-keys:/vault/keys" in vault
    assert "vault-orch-token:/vault/orch" in vault
    assert "test -s /vault/orch/orchestrator_token" in vault


def test_auto_init_issues_scoped_token_not_root_on_orch_volume():
    text = (REPO_ROOT / "services" / "vault" / "auto-init.sh").read_text(encoding="utf-8")
    assert "vault policy write orchestrator" in text
    assert "token create -policy=orchestrator" in text
    assert '"$ORCH_DIR/orchestrator_token"' in text
    assert 'ORCH_DIR="/vault/orch"' in text
    assert "ORCH_DIR/root_token" not in text
    assert 'printf \'%s\' "$ROOT_TOKEN" > "$ORCH_DIR' not in text


def test_policy_is_limited_to_factory_secrets():
    text = (REPO_ROOT / "services" / "vault" / "orchestrator-policy.hcl").read_text(encoding="utf-8")
    assert 'path "secret/data/factory/secrets"' in text
    assert 'path "secret/metadata/factory/secrets"' in text
    assert "*" not in text
    assert "sys/" not in text


def test_makefile_vault_export_does_not_pass_secrets_via_argv():
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = text.split("vault-export-keys:", 1)[1].split("\ndown:", 1)[0]
    assert "-w" not in recipe
    assert "VAULT_ROOT_TOKEN" in recipe
    assert "keychain_set.py" in recipe
    assert "add-generic-password" not in recipe
    assert "root_token" not in recipe


def test_keychain_set_main_reads_stdin_not_argv(monkeypatch):
    captured: dict = {}

    def fake_set(service: str, account: str, value: bytes) -> None:
        captured["service"] = service
        captured["account"] = account
        captured["value"] = value

    monkeypatch.setattr(ks, "set_generic_password", fake_set)

    class _Stdin:
        buffer = io.BytesIO(b"unseal-from-stdin\n")

    monkeypatch.setattr(ks.sys, "stdin", _Stdin())
    assert ks.main(["dentroio-factory", "VAULT_UNSEAL_KEY"]) == 0
    assert captured["value"] == b"unseal-from-stdin"
    assert captured["account"] == "VAULT_UNSEAL_KEY"


def test_keychain_set_delete_does_not_read_stdin(monkeypatch):
    called = {}

    def fake_delete(service: str, account: str) -> None:
        called["service"] = service
        called["account"] = account

    monkeypatch.setattr(ks, "delete_generic_password", fake_delete)
    assert ks.main(["--delete", "dentroio-factory", "VAULT_ROOT_TOKEN"]) == 0
    assert called["account"] == "VAULT_ROOT_TOKEN"
