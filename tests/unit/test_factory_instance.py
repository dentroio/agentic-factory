"""WO-1107: FACTORY_INSTANCE namespaces prefs, Keychain service, logs and ports.

With no instance set, every value must be the one the engine always used so an
existing install is unchanged.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "factory_instance.sh"
KEYS = [
    "FACTORY_KEYCHAIN_SERVICE",
    "FACTORY_PREFS",
    "FACTORY_LOG_DIR",
    "FACTORY_PORT_STATUS",
    "FACTORY_PORT_ORCHESTRATOR",
    "FACTORY_PORT_VAULT",
]


def _values(**env):
    base = {k: v for k, v in os.environ.items() if not k.startswith("FACTORY_")}
    base.update(env)
    cmd = f'source "{SCRIPT}"; ' + "; ".join(f'echo {k}=${k}' for k in KEYS)
    out = subprocess.run(["bash", "-c", cmd], env=base, capture_output=True, text=True, check=True)
    return dict(line.split("=", 1) for line in out.stdout.splitlines())


def test_default_instance_is_unchanged():
    v = _values()
    home = Path(os.environ["HOME"])
    assert v["FACTORY_KEYCHAIN_SERVICE"] == "dentroio-factory"
    assert v["FACTORY_PREFS"] == str(home / ".config/factory-agent/prefs")
    assert v["FACTORY_LOG_DIR"] == str(home / "Library/Logs/factory-agent")
    assert (v["FACTORY_PORT_STATUS"], v["FACTORY_PORT_ORCHESTRATOR"], v["FACTORY_PORT_VAULT"]) == (
        "8099",
        "8100",
        "8201",
    )


def test_named_instance_gets_its_own_names_and_ports():
    v = _values(FACTORY_INSTANCE="aegisflux", FACTORY_PORT_OFFSET="100")
    home = Path(os.environ["HOME"])
    assert v["FACTORY_KEYCHAIN_SERVICE"] == "dentroio-factory-aegisflux"
    assert v["FACTORY_PREFS"] == str(home / ".config/factory-agent-aegisflux/prefs")
    assert v["FACTORY_LOG_DIR"] == str(home / "Library/Logs/factory-agent-aegisflux")
    assert v["FACTORY_PORT_STATUS"] == "8199"
    assert v["FACTORY_PORT_ORCHESTRATOR"] == "8200"
    assert v["FACTORY_PORT_VAULT"] == "8301"


def test_explicit_overrides_win():
    v = _values(FACTORY_INSTANCE="x", FACTORY_PREFS="/tmp/p", FACTORY_PORT_STATUS="9000")
    assert v["FACTORY_PREFS"] == "/tmp/p"
    assert v["FACTORY_PORT_STATUS"] == "9000"


def test_compose_ports_come_from_the_instance_variables():
    text = (ROOT / "docker-compose.status.yml").read_text()
    for var, port in (("STATUS", "8099"), ("ORCHESTRATOR", "8100"), ("VAULT", "8201")):
        assert f"${{FACTORY_PORT_{var}:-{port}}}" in text


def test_scripts_do_not_hardcode_the_keychain_service():
    for name in ("factory-env.sh", "agent-setup.sh"):
        assert '-s "dentroio-factory"' not in (ROOT / "scripts" / name).read_text()
