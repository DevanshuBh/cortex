# Runbook: CostPerQueryHigh

**Meaning.** The median notional cost per question is above $0.01 at reference prices. On local models real spend
is zero; the number matters because it tracks tokens, which drive latency, GPU time and any hosted spend.

**First five minutes.** "Cost doubled last week — why?"
1. `SELECT step, tier, avg(input_tokens), avg(output_tokens), count(*) FROM llm_calls WHERE created_at > now() -
   interval '1 day' GROUP BY 1, 2 ORDER BY 3 DESC;` — which step grew?
2. Routing mix: did `CORTEX_ROUTING_POLICY` change to `large-only`?
3. Longer contexts: larger chunks or more evidence per answer?

**Fixes.** Return to the `routed` policy; reduce evidence passed to the Analyst; cap steps; add the semantic cache
(staff step S.7) for repeated questions.
