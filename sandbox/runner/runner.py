"""sandbox-runner: runs untrusted Python in a throwaway, locked-down container (design §8.6, guide step 4.3).

The only component with access to the Docker socket. It accepts code text and nothing else: the image, flags,
limits and runtime are fixed here, never taken from the request. Standard library only.

    POST /run  {"code": "...", "timeout_s": 10}   (Authorization: Bearer <SANDBOX_RUNNER_TOKEN>)
    -> {"stdout", "stderr", "exit_code", "timed_out", "truncated", "duration_ms"}
"""

from __future__ import annotations

import hmac
import json
import os
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

IMAGE = os.environ.get("SANDBOX_IMAGE", "cortex-sandbox:latest")
RUNTIME = os.environ.get("SANDBOX_RUNTIME", "")  # e.g. "runsc" for gVisor where installed
TOKEN = os.environ.get("SANDBOX_RUNNER_TOKEN", "")
MAX_OUTPUT = 64 * 1024
MAX_CODE = 16 * 1024
MAX_TIMEOUT = 30.0
MAX_CONCURRENT = int(os.environ.get("SANDBOX_MAX_CONCURRENT", "2"))
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


BACKEND = os.environ.get("SANDBOX_BACKEND", "docker")  # "docker" (Compose) or "kubernetes" (k3s, gVisor)
K8S_NAMESPACE = os.environ.get("SANDBOX_NAMESPACE", "cortex-sandbox")


def kubectl_args(name: str) -> list[str]:
    """One throwaway pod per job under gVisor. The namespace has a deny-all NetworkPolicy and no service account
    token is mounted; the runner's own RBAC only allows creating/deleting pods there (deploy/k8s)."""
    overrides = {
        "apiVersion": "v1",
        "spec": {
            "runtimeClassName": "gvisor",
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,
            "restartPolicy": "Never",
            "securityContext": {"runAsUser": 65534, "runAsGroup": 65534, "runAsNonRoot": True,
                                "seccompProfile": {"type": "RuntimeDefault"}},
            "containers": [{
                "name": name, "image": IMAGE, "stdin": True, "stdinOnce": True,
                "env": [{"name": "HOME", "value": "/tmp"}],
                "resources": {"limits": {"cpu": "500m", "memory": "256Mi", "ephemeral-storage": "64Mi"},
                              "requests": {"cpu": "100m", "memory": "64Mi"}},
                "securityContext": {"readOnlyRootFilesystem": True, "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"]}},
                "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
            }],
            "volumes": [{"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "64Mi"}}],
        },
    }
    return ["kubectl", "run", name, "-n", K8S_NAMESPACE, "--rm", "-i", "--quiet", "--restart=Never",
            f"--image={IMAGE}", f"--overrides={json.dumps(overrides)}", "--pod-running-timeout=60s"]


def sandbox_args(name: str) -> list[str]:
    return kubectl_args(name) if BACKEND == "kubernetes" else docker_args(name)


def kill(name: str) -> None:
    cmd = (["kubectl", "delete", "pod", name, "-n", K8S_NAMESPACE, "--grace-period=0", "--force"]
           if BACKEND == "kubernetes" else ["docker", "kill", name])
    subprocess.run(cmd, capture_output=True, timeout=15, check=False)


def docker_args(name: str) -> list[str]:
    args = [
        "docker", "run", "--rm", "-i", "--name", name,
        "--network", "none",                      # no network at all
        "--read-only",                            # read-only root filesystem
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--pids-limit", "64",                     # fork bombs hit this
        "--memory", "256m", "--memory-swap", "256m",
        "--cpus", "0.5",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "65534:65534",                  # nobody
        "--ulimit", "nofile=64:64",
        "--ulimit", "fsize=10485760:10485760",
        "--env", "HOME=/tmp",                     # nothing from the runner's environment is passed
        "--stop-timeout", "1",
    ]
    if RUNTIME:
        args += ["--runtime", RUNTIME]
    return [*args, IMAGE]


def _read_capped(stream: Any, out: dict[str, Any], key: str) -> None:
    buf = bytearray()
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        if len(buf) < MAX_OUTPUT:
            buf.extend(chunk[: MAX_OUTPUT - len(buf)])
        else:
            out["truncated"] = True  # keep draining so the process is not blocked on a full pipe
    out[key] = buf.decode("utf-8", errors="replace")


def run(code: str, timeout_s: float = 10.0) -> dict[str, Any]:
    if len(code.encode()) > MAX_CODE:
        return {"stdout": "", "stderr": "code too large", "exit_code": -1, "timed_out": False,
                "truncated": False, "duration_ms": 0}
    timeout_s = max(1.0, min(float(timeout_s), MAX_TIMEOUT))
    name = f"cortex-sbx-{uuid.uuid4().hex[:12]}"
    result: dict[str, Any] = {"stdout": "", "stderr": "", "truncated": False, "timed_out": False}
    started = time.monotonic()
    with _slots:
        proc = subprocess.Popen(sandbox_args(name), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        readers = [threading.Thread(target=_read_capped, args=(proc.stdout, result, "stdout"), daemon=True),
                   threading.Thread(target=_read_capped, args=(proc.stderr, result, "stderr"), daemon=True)]
        for t in readers:
            t.start()
        try:
            assert proc.stdin is not None
            proc.stdin.write(code.encode())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        try:
            proc.wait(timeout=timeout_s + 3)  # + container start-up
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
            kill(name)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        for t in readers:
            t.join(timeout=5)
    result["exit_code"] = proc.returncode if not result["timed_out"] else -9
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    if result["exit_code"] == 137 and not result["timed_out"]:
        result["stderr"] += "\n[killed: memory limit]"
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "cortex-sandbox-runner"

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/run":
            self._send(404, {"error": "not found"})
            return
        auth = self.headers.get("Authorization", "")
        if not TOKEN or not hmac.compare_digest(auth, f"Bearer {TOKEN}"):
            self._send(401, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_CODE * 2:
            self._send(413, {"error": "request too large"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            code = str(body["code"])
            timeout_s = float(body.get("timeout_s", 10))
        except (ValueError, KeyError, TypeError):
            self._send(400, {"error": "expected {code, timeout_s}"})
            return
        self._send(200, run(code, timeout_s))

    def log_message(self, fmt: str, *args: Any) -> None:  # one JSON line per request
        print(json.dumps({"msg": fmt % args, "client": self.client_address[0]}), flush=True)


def main() -> None:
    if not TOKEN:
        raise SystemExit("SANDBOX_RUNNER_TOKEN must be set")
    port = int(os.environ.get("PORT", "8090"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # noqa: S104 - internal network only


if __name__ == "__main__":
    main()
