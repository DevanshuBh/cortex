/**
 * Server-sent events over fetch (EventSource cannot send an Authorization header).
 * Reconnects with exponential backoff and resumes with Last-Event-ID, so no token is lost on a flaky network.
 */

import { tokenStore } from "./auth";
import { config } from "./config";

export interface SseEvent {
  id: string | null;
  event: string;
  data: unknown;
}

export type ConnectionState = "connecting" | "open" | "reconnecting" | "closed";

export const TERMINAL = new Set(["done", "error", "cancelled"]);

/** Parse SSE text incrementally. Returns complete events and the unconsumed remainder. */
export function parseSse(buffer: string): { events: SseEvent[]; rest: string } {
  const events: SseEvent[] = [];
  const blocks = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let id: string | null = null;
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const idx = line.indexOf(":");
      const field = idx === -1 ? line : line.slice(0, idx);
      const value = idx === -1 ? "" : line.slice(idx + 1).replace(/^ /, "");
      if (field === "id") id = value;
      else if (field === "event") event = value;
      else if (field === "data") dataLines.push(value);
    }
    if (!dataLines.length) continue;
    const raw = dataLines.join("\n");
    let data: unknown = raw;
    try {
      data = JSON.parse(raw);
    } catch {
      /* plain text */
    }
    events.push({ id, event, data });
  }
  return { events, rest };
}

export interface StreamOptions {
  onEvent: (e: SseEvent) => void;
  onState?: (s: ConnectionState) => void;
  signal: AbortSignal;
  maxRetries?: number;
  fetchImpl?: typeof fetch;
}

export async function streamTask(taskId: string, opts: StreamOptions): Promise<void> {
  const doFetch = opts.fetchImpl ?? fetch;
  let lastId: string | null = null;
  let attempt = 0;
  const max = opts.maxRetries ?? 8;
  while (!opts.signal.aborted) {
    opts.onState?.(attempt === 0 ? "connecting" : "reconnecting");
    try {
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      const token = tokenStore.get();
      if (token) headers.Authorization = `Bearer ${token}`;
      if (lastId) headers["Last-Event-ID"] = lastId;
      const res = await doFetch(`${config.apiUrl}/v1/tasks/${taskId}/events`, { headers, signal: opts.signal });
      if (!res.ok || !res.body) throw new Error(`stream failed (${res.status})`);
      opts.onState?.("open");
      attempt = 0;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSse(buffer);
        buffer = parsed.rest;
        for (const ev of parsed.events) {
          if (ev.id) lastId = ev.id;
          opts.onEvent(ev);
          if (TERMINAL.has(ev.event)) {
            opts.onState?.("closed");
            return;
          }
        }
      }
    } catch (e) {
      if (opts.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) break;
    }
    attempt += 1;
    if (attempt > max) break;
    const delay = Math.min(10_000, 500 * 2 ** (attempt - 1)) * (0.75 + Math.random() * 0.5);
    await new Promise((r) => setTimeout(r, delay));
  }
  opts.onState?.("closed");
}
