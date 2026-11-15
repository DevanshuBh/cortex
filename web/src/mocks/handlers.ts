import { http, HttpResponse } from "msw";
import { config } from "@/lib/config";
import { demoDocuments, demoEvidence, demoRuns } from "./fixtures";
import { type DemoEvent, findScenario, offScriptEvents, replayDelays, scenarios } from "./scenarios";

const API = config.apiUrl;
const NOT_FOUND = /airspeed|kafka|weather|price/i;
const tasks = new Map<string, string>();

function sse(events: { event: string; data: unknown }[]): string {
  return events.map((e, i) => `id: ${Date.now()}-${i}\nevent: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`).join("");
}

function answerEvents(question: string): DemoEvent[] {
  const sc = findScenario(question);
  if (sc) return [...sc.events, { t: 0, event: "done", data: {} }];
  return [...offScriptEvents(NOT_FOUND.test(question)), { t: 0, event: "done", data: {} }];
}

/** Every passage the demo can open: the built-in fixtures plus everything cited in the recordings. */
function allEvidence() {
  const out = new Map(demoEvidence.map((e) => [e.chunk_id, e]));
  for (const sc of scenarios)
    for (const ev of sc.events)
      if (ev.event === "evidence" || ev.event === "answer")
        for (const e of ((ev.data.items ?? ev.data.evidence) as typeof demoEvidence | undefined) ?? []) out.set(e.chunk_id, e);
  return out;
}

export const handlers = [
  http.get(`${API}/v1/me`, () => HttpResponse.json({ user_id: "demo-user", tenant_id: "k8s-docs", roles: ["admin", "member"] })),
  http.get(`${API}/v1/documents`, ({ request }) => {
    const q = new URL(request.url).searchParams.get("q")?.toLowerCase() ?? "";
    const items = demoDocuments.filter((d) => d.title.toLowerCase().includes(q));
    return HttpResponse.json({ items, total: items.length, limit: 200, offset: 0 });
  }),
  http.post(`${API}/v1/documents`, () =>
    HttpResponse.json({ document_id: crypto.randomUUID(), upload_url: `${API}/demo-upload`, upload_headers: {}, expires_in: 900 }, { status: 201 })),
  http.put(`${API}/demo-upload`, () => new HttpResponse(null, { status: 200 })),
  http.post(`${API}/v1/documents/:id/complete`, () => HttpResponse.json({ task_id: crypto.randomUUID(), status: "queued", created: true }, { status: 202 })),
  http.delete(`${API}/v1/documents/:id`, () => HttpResponse.json({ task_id: crypto.randomUUID(), status: "queued", created: true }, { status: 202 })),
  http.post(`${API}/v1/ask`, async ({ request }) => {
    const body = (await request.json()) as { question: string };
    const id = crypto.randomUUID();
    tasks.set(id, body.question);
    return HttpResponse.json({ task_id: id, status: "queued", created: true }, { status: 202 });
  }),
  http.get(`${API}/v1/tasks/:id/events`, ({ params }) => {
    const events = answerEvents(tasks.get(String(params.id)) ?? "");
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        const delays = replayDelays(events);
        for (const [i, e] of events.entries()) {
          controller.enqueue(encoder.encode(sse([e])));
          await new Promise((r) => setTimeout(r, delays[i]));
        }
        controller.close();
      },
    });
    return new HttpResponse(stream, { headers: { "Content-Type": "text/event-stream" } });
  }),
  http.post(`${API}/v1/tasks/:id/cancel`, ({ params }) => HttpResponse.json({ task_id: String(params.id), status: "cancelled", created: false }, { status: 202 })),
  http.post(`${API}/v1/answers/:id/feedback`, () => new HttpResponse(null, { status: 204 })),
  http.get(`${API}/v1/chunks/:id`, ({ params }) => {
    const e = allEvidence().get(String(params.id));
    if (!e) return HttpResponse.json({ title: "Not found", status: 404, detail: "passage not found" }, { status: 404 });
    return HttpResponse.json({ id: e.chunk_id, document_id: e.document_id, document_title: e.title, position: e.n, heading_path: e.heading,
      text: e.text, char_start: 0, char_end: e.text.length, filename: "demo.md", mime: "text/markdown", page: null });
  }),
  http.get(`${API}/v1/admin/eval-runs`, () => HttpResponse.json(demoRuns)),
  http.get(`${API}/v1/admin/usage`, () => HttpResponse.json({
    by_tier: [
      { tier: "small", provider: "ollama", calls: 412, input_tokens: 391000, output_tokens: 52000, cost_usd: 0.021, errors: 1 },
      { tier: "large", provider: "ollama", calls: 151, input_tokens: 462000, output_tokens: 31000, cost_usd: 0.469, errors: 0 },
    ],
    daily: [], routes: [], feedback: [{ day: "2026-11-15", up: 9, down: 2 }],
    cost_note: "Costs are notional, at reference list prices; local models cost nothing to run.",
  })),
];
