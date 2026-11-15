import { describe, expect, it } from "vitest";
import { applyEvent, type Turn } from "./research";
import { validateFile } from "./upload";

const base: Turn = {
  id: "x", taskId: "t", question: "q", status: "queued", streamed: "", answer: null, evidence: [], graphPaths: [], steps: [],
  code: null, route: null, partial: false, notFound: false, stopReason: null, tokens: 0, costUsd: 0, latencyMs: null,
  error: null, feedback: null,
};

describe("applyEvent", () => {
  it("streams tokens, then the final answer replaces them", () => {
    let t = applyEvent(base, { id: "1", event: "token", data: { text: "A Po" } });
    t = applyEvent(t, { id: "2", event: "token", data: { text: "d" } });
    expect(t.streamed).toBe("A Pod");
    t = applyEvent(t, { id: "3", event: "answer", data: { answer: "A Pod [1].", evidence: [], graph_paths: [], route: "content",
      partial: true, not_found: false, stop_reason: "step_budget", input_tokens: 10, output_tokens: 5, cost_usd: 0.1, latency_ms: 900 } });
    expect(t.answer).toBe("A Pod [1].");
    expect(t.partial).toBe(true);
    expect(t.tokens).toBe(15);
    expect(applyEvent(t, { id: "4", event: "done", data: {} }).status).toBe("done");
  });

  it("de-duplicates evidence and records the route from the first step", () => {
    const ev = { n: 1, chunk_id: "c1", document_id: "d", title: "T", heading: "H", text: "x", source: "dense" };
    let t = applyEvent(base, { id: "1", event: "evidence", data: { items: [ev] } });
    t = applyEvent(t, { id: "2", event: "evidence", data: { items: [ev] } });
    expect(t.evidence).toHaveLength(1);
    t = applyEvent(t, { id: "3", event: "step", data: { t: 0, agent: "supervisor", action: "route: both", new_evidence: 0, detail: {},
      steps_used: 0, tokens_used: 20, cost_usd: 0, remaining: { steps: 8, tokens: 1, seconds: 1 } } });
    expect(t.route).toBe("both");
  });

  it("shows errors from the stream", () => {
    expect(applyEvent(base, { id: "1", event: "error", data: { message: "boom" } })).toMatchObject({ status: "error", error: "boom" });
  });
});

describe("validateFile", () => {
  it("accepts supported files and rejects others", () => {
    expect(validateFile(new File(["# hi"], "a.md"))).toBeNull();
    expect(validateFile(new File(["x"], "a.exe"))).toMatch(/Unsupported/);
    expect(validateFile(new File([], "empty.txt"))).toMatch(/empty/);
  });
});
