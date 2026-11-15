"""Sandbox escape tests (guide step 4.3). Every attempt must fail safely.

Runs the real runner against the real ``cortex-sandbox`` image:  pytest -m sandbox
(build the image first: docker compose build sandbox-image).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

pytestmark = pytest.mark.sandbox

RUNNER = Path(__file__).resolve().parents[3] / "sandbox" / "runner" / "runner.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sandbox_runner", RUNNER)
    assert spec
    assert spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run() -> Any:
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    image = subprocess.run(
        ["docker", "image", "inspect", "cortex-sandbox:latest"], capture_output=True, check=False
    )
    if image.returncode != 0:
        pytest.skip("cortex-sandbox:latest not built")
    os.environ.setdefault("SANDBOX_IMAGE", "cortex-sandbox:latest")
    return _load_runner().run


def test_normal_code_runs(run: Any) -> None:
    r = run("print(sum(range(10)))")
    assert r["exit_code"] == 0
    assert r["stdout"].strip() == "45"


def test_no_network(run: Any) -> None:
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('CONNECTED')\n"
        "except OSError as e:\n"
        "    print('blocked', type(e).__name__)\n"
        "try:\n"
        "    socket.getaddrinfo('example.com', 80)\n"
        "    print('RESOLVED')\n"
        "except OSError:\n"
        "    print('no dns')\n"
    )
    r = run(code)
    assert "CONNECTED" not in r["stdout"]
    assert "RESOLVED" not in r["stdout"]
    assert "blocked" in r["stdout"]
    assert "no dns" in r["stdout"]


def test_no_secrets_visible(run: Any) -> None:
    os.environ["CORTEX_TEST_SECRET"] = "s3cr3t-value"  # set in the runner's environment...
    r = run("import os, json; print(json.dumps(dict(os.environ)))")
    assert "s3cr3t-value" not in r["stdout"]  # ...and never passed into the sandbox
    assert "CORTEX" not in r["stdout"]
    assert "AWS" not in r["stdout"]


def test_no_docker_socket_or_host_mounts(run: Any) -> None:
    r = run(
        "import os; print(os.path.exists('/var/run/docker.sock'), os.path.exists('/app'), os.listdir('/'))"
    )
    assert r["stdout"].startswith("False False")


def test_root_filesystem_is_read_only(run: Any) -> None:
    code = (
        "for p in ('/etc/evil', '/usr/local/lib/evil', '/evil'):\n"
        "    try:\n"
        "        open(p, 'w').write('x'); print('WROTE', p)\n"
        "    except OSError as e:\n"
        "        print('denied', p)\n"
        "open('/tmp/ok.txt', 'w').write('fine'); print('tmp ok')\n"
    )
    r = run(code)
    assert "WROTE" not in r["stdout"]
    assert r["stdout"].count("denied") == 3
    assert "tmp ok" in r["stdout"]


def test_runs_as_nobody_without_capabilities(run: Any) -> None:
    r = run("import os; print(os.getuid(), os.getgid()); print(open('/proc/self/status').read())")
    lines = r["stdout"].splitlines()
    assert lines[0] == "65534 65534"
    cap_eff = next(line for line in lines if line.startswith("CapEff:"))
    assert int(cap_eff.split()[1], 16) == 0
    assert any(line.startswith("NoNewPrivs:") and line.split()[1] == "1" for line in lines)


def test_infinite_loop_is_killed(run: Any) -> None:
    r = run("while True: pass", timeout_s=3)
    assert r["timed_out"]
    assert r["exit_code"] != 0
    assert r["duration_ms"] < 30_000


def test_fork_bomb_is_contained(run: Any) -> None:
    code = (
        "import os\n"
        "n = 0\n"
        "try:\n"
        "    while True:\n"
        "        if os.fork() == 0:\n"
        "            import time; time.sleep(30); os._exit(0)\n"
        "        n += 1\n"
        "except OSError:\n"
        "    print('fork refused after', n)\n"
    )
    r = run(code, timeout_s=8)
    assert "fork refused after" in r["stdout"]
    assert int(r["stdout"].split()[-1]) < 64


def test_memory_bomb_is_killed(run: Any) -> None:
    r = run("x = bytearray(1024 * 1024 * 1024); print('allocated')", timeout_s=10)
    assert "allocated" not in r["stdout"]
    assert r["exit_code"] != 0


def test_huge_output_is_truncated(run: Any) -> None:
    r = run("import sys\nfor _ in range(200000): sys.stdout.write('A' * 100 + '\\n')", timeout_s=10)
    assert r["truncated"]
    assert len(r["stdout"].encode()) <= 64 * 1024


def test_code_size_limit(run: Any) -> None:
    r = run("#" * 20_000)
    assert r["exit_code"] == -1
    assert "too large" in r["stderr"]
