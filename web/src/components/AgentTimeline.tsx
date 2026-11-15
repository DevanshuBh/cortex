"use client";

import { Bot, Code2, Search, Sparkles, Waypoints } from "lucide-react";
import type { Turn } from "@/lib/research";
import { Badge } from "./ui";

const ICONS: Record<string, typeof Bot> = { researcher: Search, analyst: Sparkles, coder: Code2, supervisor: Waypoints };

export function BudgetMeter({ turn, budget }: { turn: Turn; budget: { steps: number; tokens: number } }) {
  const last = turn.steps.at(-1);
  const stepsUsed = last?.steps_used ?? 0;
  const tokensUsed = turn.tokens || last?.tokens_used || 0;
  const bars = [
    { label: "Steps", used: stepsUsed, max: budget.steps },
    { label: "Tokens", used: tokensUsed, max: budget.tokens },
  ];
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {bars.map((b) => {
        const pct = Math.min(100, Math.round((b.used / b.max) * 100));
        return (
          <div key={b.label}>
            <div className="mb-1 flex justify-between text-xs text-[var(--color-muted)]">
              <span>{b.label}</span>
              <span>{b.used.toLocaleString()} / {b.max.toLocaleString()}</span>
            </div>
            <div role="meter" aria-label={`${b.label} used`} aria-valuemin={0} aria-valuemax={b.max} aria-valuenow={b.used}
              className="h-1.5 overflow-hidden rounded-full bg-[var(--color-surface-2)]">
              <div className={pct > 85 ? "h-full bg-[var(--color-warning)]" : "h-full bg-[var(--color-accent)]"} style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function AgentTimeline({ turn, budget }: { turn: Turn; budget: { steps: number; tokens: number } }) {
  const latest = turn.steps.at(-1);
  return (
    <section aria-label="Agent activity" className="space-y-4">
      <BudgetMeter turn={turn} budget={budget} />
      <p className="text-xs text-[var(--color-muted)]">
        Notional cost so far: ${turn.costUsd.toFixed(5)} (reference prices; local models cost nothing to run)
      </p>
      {turn.partial && (
        <div className="rounded-[var(--radius-md)] border border-[var(--color-warning)] p-3 text-sm">
          <strong>Partial answer — budget reached.</strong> The run stopped ({turn.stopReason?.replace(/_/g, " ")}) and
          answered from the evidence it had.
        </div>
      )}
      {/* Polite live region: screen readers hear progress without being interrupted */}
      <div aria-live="polite" className="sr-only">{latest ? `${latest.agent}: ${latest.action}` : ""}</div>
      <ol className="relative space-y-3 border-l border-[var(--color-border)] pl-4">
        {turn.steps.map((s, i) => {
          const Icon = ICONS[s.agent] ?? Bot;
          return (
            <li key={i} className="relative">
              <span aria-hidden className="absolute -left-[25px] top-0.5 grid h-4 w-4 place-items-center rounded-full bg-[var(--color-surface)]">
                <Icon className="h-3.5 w-3.5 text-[var(--color-accent)]" />
              </span>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium capitalize">{s.agent}</span>
                <span className="text-[var(--color-muted)]">{s.action}</span>
                {s.new_evidence > 0 && <Badge tone="success">+{s.new_evidence} evidence</Badge>}
              </div>
              <div className="text-xs text-[var(--color-muted)]">
                {s.t.toFixed(1)} s · {s.tokens_used.toLocaleString()} tokens
              </div>
            </li>
          );
        })}
        {turn.status === "running" && <li className="text-sm text-[var(--color-muted)]">Working…</li>}
      </ol>
      {turn.code && (
        <div>
          <h3 className="mb-1 text-sm font-medium">Code executed in the sandbox</h3>
          <p className="mb-2 text-xs text-[var(--color-muted)]">No network, read-only filesystem, CPU, memory and time limits.</p>
          <pre className="overflow-x-auto rounded-[var(--radius-md)] bg-[var(--color-surface-2)] p-3 font-mono text-xs">{turn.code.code}</pre>
          <pre className="mt-2 overflow-x-auto rounded-[var(--radius-md)] border border-[var(--color-border)] p-3 font-mono text-xs">
            {turn.code.result.stdout || turn.code.result.stderr || "(no output)"}
          </pre>
        </div>
      )}
    </section>
  );
}
