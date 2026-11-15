/**
 * Demo scenarios replayed by the static demo (GitHub Pages has no model server).
 *
 * `recorded.json` holds answers recorded from the real system by `backend/scripts/record_demo.py` — every step,
 * passage, graph path and token exactly as the pipeline emitted them. Until a recording exists, a single built-in
 * example in the same shape is used.
 */
import recorded from "./recorded.json";
import { demoAnswer, demoEvidence, demoGraphPaths, demoSteps } from "./fixtures";

export type DemoEvent = { t: number; event: string; data: Record<string, unknown> };
export type Scenario = { question: string; events: DemoEvent[] };

type Recording = { recorded_at: string | null; models?: { small: string; large: string }; scenarios: Scenario[] };
const recording = recorded as Recording;

const builtin: Scenario = {
  question: "What does a Deployment manage, and what do those objects in turn keep running?",
  events: [
    { t: 0, event: "status", data: { status: "running" } },
    ...demoSteps.map((s) => ({ t: s.t, event: "step", data: s as unknown as Record<string, unknown> })),
    { t: 3.2, event: "evidence", data: { items: demoEvidence } },
    ...demoAnswer.split(/(?<= )/).map((w) => ({ t: 3.4, event: "token", data: { text: w } })),
    { t: 8.4, event: "answer", data: {
      answer: demoAnswer, evidence: demoEvidence, graph_paths: demoGraphPaths, route: "relationship", partial: false,
      not_found: false, stop_reason: null, steps: 3, input_tokens: 3920, output_tokens: 162, cost_usd: 0.00366, latency_ms: 8400 } },
  ],
};

export const isRecorded = recording.scenarios.length > 0;
export const recordedAt = recording.recorded_at;
export const recordedModels = recording.models ?? null;
export const scenarios: Scenario[] = isRecorded ? recording.scenarios : [builtin];
export const sampleQuestions = scenarios.map((s) => s.question);

const STOP = new Set("a an and are as at be by do does for from how i in is it of on or that the this to what when which who why with".split(" "));
const words = (s: string) => new Set(s.toLowerCase().match(/[a-z0-9]+/g)?.filter((w) => !STOP.has(w)) ?? []);

/** The recorded scenario this question asks for, if any (exact, or near-identical wording). */
export function findScenario(question: string): Scenario | null {
  const q = words(question);
  let best: Scenario | null = null;
  let bestScore = 0;
  for (const s of scenarios) {
    const w = words(s.question);
    const shared = [...q].filter((x) => w.has(x)).length;
    const score = shared / Math.max(1, new Set([...q, ...w]).size);
    if (score > bestScore) [best, bestScore] = [s, score];
  }
  return bestScore >= 0.6 ? best : null;
}

/** Answers for questions outside the recordings: the demo says what it is instead of inventing an answer. */
export function offScriptEvents(notFound: boolean): DemoEvent[] {
  const answer = notFound
    ? "Not found in your documents."
    : "This public demo has no model server behind it, so it can only replay answers recorded from the real system. " +
      "Pick one of the sample questions, or run CORTEX locally (see the README) to ask anything.";
  return [
    { t: 0, event: "step", data: demoSteps[0] as unknown as Record<string, unknown> },
    { t: 0.6, event: "answer", data: { answer, evidence: [], graph_paths: [], route: notFound ? "content" : "demo",
      partial: false, not_found: notFound, stop_reason: null, steps: 1, input_tokens: 0, output_tokens: 0, cost_usd: 0, latency_ms: 0 } },
  ];
}

/** Replay pacing: keep the real order and rhythm, but squeeze long model waits so a visitor isn't left waiting. */
export function replayDelays(events: DemoEvent[]): number[] {
  const tokens = events.filter((e) => e.event === "token").length;
  const perToken = tokens ? Math.min(40, 3500 / tokens) : 0;
  return events.map((e, i) => {
    if (e.event === "token") return perToken;
    const gap = i + 1 < events.length ? (events[i + 1]!.t - e.t) * 1000 : 0;
    return Math.max(150, Math.min(900, gap));
  });
}
