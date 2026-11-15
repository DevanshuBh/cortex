# Runbook: LoopGuardTriggersSpiking

**Meaning.** More than 20 % of answers in 15 minutes stopped on a guard (step, token or time budget, no progress,
or a repeated tool call) and were marked partial.

**First five minutes.**
1. `cortex_loop_guard_triggers_total` by `reason`. Which guard?
2. Open two partial answers in the UI (Agent activity tab): what did the agents repeat?

**Fixes by reason.**
- `no_progress` / `repeated_tool_call` → the planner keeps proposing useless follow-ups. Check the assess prompt
  version in `llm_calls.prompt_version`; a recent prompt change is the usual cause.
- `token_budget` → contexts grew (bigger chunks, more evidence). Check `CORTEX_RETRIEVAL_K` / chunk size.
- `wall_clock` → the model is slow; see the latency runbook.

The false-stop rate is tracked by the loop tests (`tests/unit/test_supervisor.py`); add a regression test for any
new pattern you find.
