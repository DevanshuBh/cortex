# ADR 0009 — Coder sandbox: throwaway locked-down containers behind a narrow runner

Status: accepted · 2026-11-15

## Decision
- Code runs in a fresh `cortex-sandbox` container per job: `--network none --read-only --tmpfs /tmp
  (noexec, 64 MB) --pids-limit 64 --memory 256m --memory-swap 256m --cpus 0.5 --cap-drop ALL
  --security-opt no-new-privileges --user 65534`, file-size and open-file ulimits, 10 s wall clock (max 30 s),
  64 KB output cap, nothing from the runner's environment passed in.
- Only `sandbox-runner` talks to Docker. It accepts code text and a timeout, nothing else, behind a shared token on
  the internal network. The Docker socket is root-equivalent; that risk is contained to one tiny stdlib service.
- k3s: the same container under gVisor (`runtimeClassName: gvisor`). AWS: a Fargate task with no task role, in a
  subnet without NAT, with egress only to VPC endpoints for ECR, CloudWatch Logs and S3 (a security group with no
  egress at all would stop the task from even pulling its image — guide correction for step 6.4).
- Side effects are recorded in `tool_effects`, so a redelivered task replays the result instead of re-running code.

## Evidence
`tests/sandbox/test_escape.py`, 11 tests, all passing: network and DNS blocked, no secrets, no Docker socket or host
paths, read-only root, uid 65534 with no capabilities, infinite loop killed, fork bomb refused before 64 processes,
1 GB allocation killed, 20 MB of output truncated to 64 KB, oversized code rejected.
gVisor is not available under Docker Desktop on Windows; the comparison under `runsc` is to run on the k3s VM.
