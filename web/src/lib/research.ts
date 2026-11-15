"use client";

import { create } from "zustand";
import { api, data, type EvidenceItem, type GraphPath } from "./api";
import { describeError } from "./errors";
import { streamTask, type ConnectionState, type SseEvent } from "./sse";

export interface Step {
  t: number;
  agent: string;
  action: string;
  new_evidence: number;
  detail: Record<string, unknown>;
  steps_used: number;
  tokens_used: number;
  cost_usd: number;
  remaining: { steps: number; tokens: number; seconds: number };
}

export type TurnStatus = "queued" | "running" | "done" | "error" | "cancelled";

export interface Turn {
  id: string; // client id
  taskId: string | null;
  question: string;
  status: TurnStatus;
  streamed: string; // tokens as they arrive
  answer: string | null; // final, grounded answer (replaces streamed text)
  evidence: EvidenceItem[];
  graphPaths: GraphPath[];
  steps: Step[];
  code: { code: string; result: { stdout?: string; stderr?: string; exit_code?: number } } | null;
  route: string | null;
  partial: boolean;
  notFound: boolean;
  stopReason: string | null;
  tokens: number;
  costUsd: number;
  latencyMs: number | null;
  error: string | null;
  feedback: -1 | 1 | null;
}

interface ResearchState {
  turns: Turn[];
  connection: ConnectionState;
  budget: { steps: number; tokens: number };
  ask: (question: string) => Promise<void>;
  stop: (turnId: string) => Promise<void>;
  rate: (turnId: string, rating: -1 | 1) => Promise<void>;
  clear: () => void;
}

const controllers = new Map<string, AbortController>();

function newTurn(question: string): Turn {
  return {
    id: crypto.randomUUID(), taskId: null, question, status: "queued", streamed: "", answer: null, evidence: [],
    graphPaths: [], steps: [], code: null, route: null, partial: false, notFound: false, stopReason: null, tokens: 0,
    costUsd: 0, latencyMs: null, error: null, feedback: null,
  };
}

export function applyEvent(turn: Turn, ev: SseEvent): Turn {
  const d = (ev.data ?? {}) as Record<string, unknown>;
  switch (ev.event) {
    case "status":
      return { ...turn, status: "running" };
    case "token":
      return { ...turn, status: "running", streamed: turn.streamed + String(d.text ?? "") };
    case "step": {
      const step = d as unknown as Step;
      const route = step.action.startsWith("route: ") ? step.action.slice(7) : turn.route;
      return { ...turn, status: "running", steps: [...turn.steps, step], route, tokens: step.tokens_used,
               costUsd: step.cost_usd };
    }
    case "evidence": {
      const items = (d.items as EvidenceItem[] | undefined) ?? [];
      const seen = new Set(turn.evidence.map((e) => e.chunk_id));
      return { ...turn, evidence: [...turn.evidence, ...items.filter((e) => !seen.has(e.chunk_id))] };
    }
    case "code":
      return { ...turn, code: d as unknown as Turn["code"] };
    case "answer":
      return {
        ...turn, answer: String(d.answer ?? ""), evidence: (d.evidence as EvidenceItem[]) ?? turn.evidence,
        graphPaths: (d.graph_paths as GraphPath[]) ?? [], route: String(d.route ?? turn.route ?? ""),
        partial: Boolean(d.partial), notFound: Boolean(d.not_found), stopReason: (d.stop_reason as string) ?? null,
        tokens: Number(d.input_tokens ?? 0) + Number(d.output_tokens ?? 0), costUsd: Number(d.cost_usd ?? 0),
        latencyMs: Number(d.latency_ms ?? 0),
      };
    case "done":
      return { ...turn, status: "done" };
    case "cancelled":
      return { ...turn, status: "cancelled" };
    case "error":
      return { ...turn, status: "error", error: String(d.message ?? "Something went wrong.") };
    default:
      return turn;
  }
}

export const useResearch = create<ResearchState>((set, get) => {
  const update = (id: string, fn: (t: Turn) => Turn) =>
    set((s) => ({ turns: s.turns.map((t) => (t.id === id ? fn(t) : t)) }));

  return {
    turns: [],
    connection: "closed",
    budget: { steps: 8, tokens: 24000 },
    async ask(question) {
      const turn = newTurn(question);
      set((s) => ({ turns: [...s.turns, turn] }));
      const ctrl = new AbortController();
      controllers.set(turn.id, ctrl);
      try {
        const accepted = data(
          await api.POST("/v1/ask", {
            body: { question, router: "llm" },
            params: { header: { "Idempotency-Key": `ask-${turn.id}` } },
          }),
        );
        update(turn.id, (t) => ({ ...t, taskId: accepted.task_id }));
        await streamTask(accepted.task_id, {
          signal: ctrl.signal,
          onState: (connection) => set({ connection }),
          onEvent: (ev) => update(turn.id, (t) => applyEvent(t, ev)),
        });
      } catch (e) {
        update(turn.id, (t) => ({ ...t, status: "error", error: describeError(e) }));
      } finally {
        controllers.delete(turn.id);
        update(turn.id, (t) => (t.status === "running" || t.status === "queued" ? { ...t, status: "error",
          error: "The connection closed before the answer finished." } : t));
      }
    },
    async stop(turnId) {
      const turn = get().turns.find((t) => t.id === turnId);
      controllers.get(turnId)?.abort();
      update(turnId, (t) => ({ ...t, status: "cancelled" }));
      if (turn?.taskId) {
        try {
          await api.POST("/v1/tasks/{task_id}/cancel", { params: { path: { task_id: turn.taskId } } });
        } catch {
          /* the UI already shows it stopped */
        }
      }
    },
    async rate(turnId, rating) {
      const turn = get().turns.find((t) => t.id === turnId);
      if (!turn?.taskId) return;
      update(turnId, (t) => ({ ...t, feedback: rating }));
      await api.POST("/v1/answers/{task_id}/feedback", {
        params: { path: { task_id: turn.taskId } },
        body: { rating },
      });
    },
    clear: () => set({ turns: [] }),
  };
});
