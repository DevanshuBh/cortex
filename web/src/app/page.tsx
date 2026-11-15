"use client";

import { ArrowUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { AgentTimeline } from "@/components/AgentTimeline";
import { AnswerCard } from "@/components/AnswerCard";
import { GraphView } from "@/components/GraphView";
import { SourcePanel } from "@/components/SourcePanel";
import { Button, EmptyState } from "@/components/ui";
import { config } from "@/lib/config";
import { useResearch } from "@/lib/research";
import { sampleQuestions } from "@/mocks/scenarios";

type Tab = "sources" | "activity" | "graph";

const LOCAL_EXAMPLES = [
  "What does a Deployment manage, and what do those objects in turn keep running?",
  "How many old ReplicaSets does a Deployment keep by default?",
  "Which component restarts a container that keeps failing its liveness probe?",
];
const EXAMPLES = config.demo ? sampleQuestions : LOCAL_EXAMPLES;

export default function ResearchPage() {
  const { turns, ask, stop, rate, budget } = useResearch();
  const [question, setQuestion] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("activity");
  const [citation, setCitation] = useState<number | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const selected = turns.find((t) => t.id === selectedId) ?? turns.at(-1) ?? null;
  const running = turns.some((t) => t.status === "running" || t.status === "queued");

  useEffect(() => {
    // block body: newer browsers return a Promise from scrollIntoView, which must not become the effect cleanup
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns.length]);

  const submit = (q: string) => {
    const text = q.trim();
    if (text.length < 3 || running) return;
    setQuestion("");
    setCitation(null);
    setTab("activity");
    setSelectedId(null);
    void ask(text);
  };

  const openCitation = (turnId: string, n: number) => {
    setSelectedId(turnId);
    setCitation(n);
    setTab("sources");
    panelRef.current?.focus(); // move focus to the opened source for keyboard users
  };

  const cited = selected?.evidence.find((e) => e.n === citation) ?? null;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
      <section aria-label="Conversation" className="flex min-h-[calc(100dvh-7rem)] flex-col">
        <div className="flex-1 space-y-3">
          {turns.length === 0 ? (
            <EmptyState title="Ask your documents a question">
              <p>Answers cite the exact passages they come from. If your documents don&apos;t contain the answer, CORTEX says so.</p>
              {config.demo && <p className="mt-2">This demo searches 347 pages of the Kubernetes documentation. Try a sample question:</p>}
              <div className="mt-4 flex flex-col gap-2">
                {EXAMPLES.map((ex) => (
                  <button key={ex} onClick={() => submit(ex)} className="rounded-[var(--radius-md)] border border-[var(--color-border)] px-3 py-2 text-left text-sm hover:border-[var(--color-accent)]">
                    {ex}
                  </button>
                ))}
              </div>
            </EmptyState>
          ) : (
            turns.map((t) => (
              <AnswerCard
                key={t.id}
                turn={t}
                selected={t.id === selected?.id}
                onSelect={() => setSelectedId(t.id)}
                onCite={(n) => openCitation(t.id, n)}
                onStop={() => void stop(t.id)}
                onRate={(r) => void rate(t.id, r)}
              />
            ))
          )}
          <div ref={endRef} />
        </div>
        <form
          className="sticky bottom-0 mt-4 bg-[var(--color-bg)] pb-2"
          onSubmit={(e) => {
            e.preventDefault();
            submit(question);
          }}
        >
          <label htmlFor="question" className="sr-only">Your question</label>
          <div className="flex items-end gap-2 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-2 focus-within:border-[var(--color-accent)]">
            <textarea
              id="question"
              ref={inputRef}
              rows={1}
              value={question}
              maxLength={2000}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(question);
                }
              }}
              placeholder="Ask about your documents…"
              className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none"
            />
            <Button type="submit" variant="primary" aria-label="Ask" disabled={running || question.trim().length < 3}>
              <ArrowUp aria-hidden className="h-4 w-4" />
            </Button>
          </div>
          <p className="mt-1 px-1 text-xs text-[var(--color-muted)]">Enter to ask · Shift+Enter for a new line</p>
        </form>
      </section>

      <aside
        ref={panelRef}
        tabIndex={-1}
        aria-label="Answer details"
        className="h-fit rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4 outline-none lg:sticky lg:top-20 lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto"
      >
        <div role="tablist" aria-label="Details" className="mb-4 flex gap-1">
          {(["activity", "sources", "graph"] as Tab[]).map((t) => (
            <Button key={t} size="sm" role="tab" aria-selected={tab === t} variant={tab === t ? "primary" : "ghost"} onClick={() => setTab(t)}>
              {t === "activity" ? "Agent activity" : t === "sources" ? "Source" : "Graph"}
            </Button>
          ))}
        </div>
        {!selected ? (
          <p className="text-sm text-[var(--color-muted)]">Details of an answer appear here: what the agents did, the cited passages and the relationships used.</p>
        ) : tab === "activity" ? (
          <AgentTimeline turn={selected} budget={budget} />
        ) : tab === "sources" ? (
          cited ? <SourcePanel evidence={cited} /> : (
            <ul className="space-y-2 text-sm">
              {selected.evidence.length === 0 && <li className="text-[var(--color-muted)]">No sources yet.</li>}
              {selected.evidence.map((e) => (
                <li key={e.chunk_id}>
                  <button className="text-left hover:underline" onClick={() => setCitation(e.n)}>
                    <span className="font-medium">[{e.n}] {e.title}</span>
                    <span className="block text-xs text-[var(--color-muted)]">{e.heading}</span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : (
          <GraphView paths={selected.graphPaths} evidence={selected.evidence} onOpen={(n) => { setCitation(n); setTab("sources"); }} />
        )}
      </aside>
    </div>
  );
}
