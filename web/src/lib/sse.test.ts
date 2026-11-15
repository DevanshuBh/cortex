import { describe, expect, it, vi } from "vitest";
import { parseSse, streamTask, type SseEvent } from "./sse";

describe("parseSse", () => {
  it("parses complete events and keeps the partial remainder", () => {
    const { events, rest } = parseSse('id: 1-0\nevent: token\ndata: {"text":"Hi"}\n\nid: 2-0\nevent: tok');
    expect(events).toEqual([{ id: "1-0", event: "token", data: { text: "Hi" } }]);
    expect(rest).toBe("id: 2-0\nevent: tok");
  });

  it("ignores comments (keep-alives) and handles CRLF", () => {
    const { events } = parseSse(": keep-alive\r\n\r\nevent: done\r\ndata: {}\r\n\r\n");
    expect(events).toEqual([{ id: null, event: "done", data: {} }]);
  });
});

function streamOf(chunks: string[], fail = false): Response {
  const enc = new TextEncoder();
  let i = 0;
  // pull-based so the connection drops only after the client has read what was sent
  const body = new ReadableStream<Uint8Array>({
    pull(c) {
      if (i < chunks.length) c.enqueue(enc.encode(chunks[i++]!));
      else if (fail) c.error(new TypeError("network dropped"));
      else c.close();
    },
  });
  return new Response(body, { status: 200 });
}

describe("streamTask", () => {
  it("reconnects with Last-Event-ID and loses nothing", async () => {
    const seen: SseEvent[] = [];
    const lastIds: (string | null)[] = [];
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const h = new Headers(init?.headers);
      lastIds.push(h.get("Last-Event-ID"));
      return lastIds.length === 1
        ? streamOf(['id: 1-0\nevent: token\ndata: {"text":"A "}\n\n', 'id: 2-0\nevent: token\ndata: {"text":"Pod"}\n\n'], true)
        : streamOf(['id: 3-0\nevent: token\ndata: {"text":" runs"}\n\n', "id: 4-0\nevent: done\ndata: {}\n\n"]);
    });
    vi.spyOn(Math, "random").mockReturnValue(0);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await streamTask("t1", { signal: new AbortController().signal, onEvent: (e) => seen.push(e), fetchImpl: fetchImpl as typeof fetch });
    vi.useRealTimers();
    expect(lastIds).toEqual([null, "2-0"]);
    expect(seen.map((e) => e.event)).toEqual(["token", "token", "token", "done"]);
  });
});
