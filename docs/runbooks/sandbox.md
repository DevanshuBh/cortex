# Runbook: SandboxUnavailable

**Meaning.** Coder-agent jobs could not reach the sandbox runner. Calculation questions still get an answer, but
without the computed result.

**First five minutes.**
1. `docker compose ps sandbox-runner` and `curl -s localhost:8090/healthz` from inside the network.
2. Runner logs: Docker socket errors? Image `cortex-sandbox:latest` missing?

**Fixes.** Rebuild the image (`docker compose build sandbox-image`), restart the runner, check the shared token
(`SANDBOX_RUNNER_TOKEN`) matches `CORTEX_SANDBOX_RUNNER_TOKEN`.

**Never** "fix" it by giving the sandbox network access or mounting host paths — run
`pytest -m sandbox` after any change; every escape test must still fail safely.
