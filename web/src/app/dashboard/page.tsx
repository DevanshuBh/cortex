"use client";

import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { api, data, type EvalRun } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { describeError } from "@/lib/errors";

type Ci = { value: number; low: number; high: number };
const SERIES = ["dense", "sparse", "fused", "reranked", "graph", "reranked+graph"];
const COLORS = ["#2f5bea", "#a35200", "#8a5cf6", "#18794e", "#c4302b", "#0e7490"];

function recallSeries(runs: EvalRun[]) {
  return runs
    .filter((r) => r.name === "retrieval")
    .slice()
    .reverse()
    .map((r) => {
      const row: Record<string, number | string> = { run: new Date(r.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit" }) };
      for (const [cfg, m] of Object.entries(r.metrics as Record<string, { "recall@10"?: Ci }>)) {
        if (m?.["recall@10"]) row[cfg] = Math.round(m["recall@10"].value * 1000) / 10;
      }
      return row;
    });
}

function policyRows(runs: EvalRun[]) {
  const latest = new Map<string, EvalRun>();
  for (const r of runs) {
    const policy = (r.config as { policy?: string }).policy;
    if (r.name.startsWith("answers") && policy && !latest.has(policy)) latest.set(policy, r);
  }
  return [...latest.entries()].map(([policy, r]) => {
    const m = r.metrics as { answered_rate?: Ci; judge_correct?: Ci; notional_cost_per_question_usd?: number; latency_ms_p50?: number };
    return {
      policy,
      answered: m.answered_rate ? Math.round(m.answered_rate.value * 1000) / 10 : null,
      correct: m.judge_correct ? Math.round(m.judge_correct.value * 1000) / 10 : null,
      cost: m.notional_cost_per_question_usd ?? null,
      p50: m.latency_ms_p50 ? m.latency_ms_p50 / 1000 : null,
    };
  });
}

export default function DashboardPage() {
  const { session } = useAuth();
  const runs = useQuery({ queryKey: ["eval-runs"], queryFn: async () => data(await api.GET("/v1/admin/eval-runs", {})), enabled: !!session?.isAdmin });
  const usage = useQuery({ queryKey: ["usage"], queryFn: async () => data(await api.GET("/v1/admin/usage", { params: { query: { days: 30 } } })), enabled: !!session?.isAdmin });

  if (!session?.isAdmin) return <EmptyState title="Admins only">Ask a team admin for access to quality and cost data.</EmptyState>;
  if (runs.isPending || usage.isPending) return <div className="grid gap-4 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-72" />)}</div>;
  if (runs.isError) return <ErrorState message={describeError(runs.error)} onRetry={() => runs.refetch()} />;
  if (usage.isError) return <ErrorState message={describeError(usage.error)} onRetry={() => usage.refetch()} />;

  const series = recallSeries(runs.data);
  const policies = policyRows(runs.data);
  const tiers = usage.data.by_tier;
  const feedback = usage.data.feedback;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Quality &amp; cost</h1>
        <p className="text-sm text-[var(--color-muted)]">{usage.data.cost_note}</p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="p-4">
          <h2 className="mb-1 font-medium">Recall@10 per evaluation run</h2>
          <p className="mb-3 text-xs text-[var(--color-muted)]">Labelled questions, % of evidence found in the top 10. Full intervals in eval/reports.</p>
          {series.length === 0 ? <p className="text-sm text-[var(--color-muted)]">No retrieval evaluations yet.</p> : (
            <div className="h-64">
              <ResponsiveContainer>
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="run" fontSize={11} stroke="var(--color-muted)" />
                  <YAxis domain={[0, 100]} unit="%" fontSize={11} stroke="var(--color-muted)" />
                  <Tooltip /><Legend />
                  {SERIES.filter((s) => series.some((r) => r[s] !== undefined)).map((s) => (
                    <Line key={s} dataKey={s} stroke={COLORS[SERIES.indexOf(s)]} strokeWidth={2} dot={{ r: 3 }} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card className="p-4">
          <h2 className="mb-1 font-medium">Routing policies: quality, cost, latency</h2>
          <p className="mb-3 text-xs text-[var(--color-muted)]">Latest answer evaluation per policy. Cost is notional (reference prices).</p>
          {policies.length === 0 ? <p className="text-sm text-[var(--color-muted)]">No answer evaluations yet.</p> : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-[var(--color-muted)]"><tr><th>Policy</th><th>Answered</th><th>Judge correct</th><th>Cost / q</th><th>p50</th></tr></thead>
              <tbody>{policies.map((p) => (
                <tr key={p.policy} className="border-t border-[var(--color-border)]">
                  <td className="py-1.5 font-medium">{p.policy}</td><td>{p.answered ?? "—"}%</td><td>{p.correct ?? "—"}{p.correct !== null && "%"}</td>
                  <td>${p.cost?.toFixed(5) ?? "—"}</td><td>{p.p50?.toFixed(1) ?? "—"} s</td>
                </tr>))}
              </tbody>
            </table>
          )}
        </Card>
        <Card className="p-4">
          <h2 className="mb-3 font-medium">Model usage (30 days)</h2>
          {tiers.length === 0 ? <p className="text-sm text-[var(--color-muted)]">No model calls yet.</p> : (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={tiers.map((t) => ({ tier: `${t.tier} (${t.provider})`, input: t.input_tokens, output: t.output_tokens }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="tier" fontSize={11} stroke="var(--color-muted)" /><YAxis fontSize={11} stroke="var(--color-muted)" />
                  <Tooltip /><Legend />
                  <Bar dataKey="input" stackId="t" fill="#2f5bea" /><Bar dataKey="output" stackId="t" fill="#18794e" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card className="p-4">
          <h2 className="mb-3 font-medium">User feedback</h2>
          {feedback.length === 0 ? <p className="text-sm text-[var(--color-muted)]">No ratings yet.</p> : (
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={feedback}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                  <XAxis dataKey="day" fontSize={11} stroke="var(--color-muted)" /><YAxis allowDecimals={false} fontSize={11} stroke="var(--color-muted)" />
                  <Tooltip /><Legend />
                  <Bar dataKey="up" fill="#18794e" name="helpful" /><Bar dataKey="down" fill="#c4302b" name="not helpful" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
