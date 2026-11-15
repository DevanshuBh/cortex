"use client";

import { Check, Copy, SearchX, Square, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import type { Turn } from "@/lib/research";
import { Markdown } from "./Markdown";
import { Badge, Button, ErrorState } from "./ui";

export function AnswerCard({ turn, selected, onSelect, onCite, onStop, onRate }: {
  turn: Turn;
  selected: boolean;
  onSelect: () => void;
  onCite: (n: number) => void;
  onStop: () => void;
  onRate: (r: -1 | 1) => void;
}) {
  const [copied, setCopied] = useState(false);
  const running = turn.status === "queued" || turn.status === "running";
  const text = turn.answer ?? turn.streamed;
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <article
      aria-label={`Answer to: ${turn.question}`}
      onClick={onSelect}
      className={`rounded-[var(--radius-lg)] border bg-[var(--color-surface)] p-4 transition-colors ${selected ? "border-[var(--color-accent)]" : "border-[var(--color-border)]"}`}
    >
      <h2 className="text-[15px] font-semibold">{turn.question}</h2>
      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--color-muted)]">
        {turn.route && <Badge tone="accent">{turn.route}</Badge>}
        {turn.partial && <Badge tone="warning">partial — budget reached</Badge>}
        {turn.status === "cancelled" && <Badge>stopped</Badge>}
        {turn.latencyMs !== null && <span>{(turn.latencyMs / 1000).toFixed(1)} s</span>}
        {turn.tokens > 0 && <span>{turn.tokens.toLocaleString()} tokens</span>}
      </div>

      <div className="mt-3 min-h-6" aria-busy={running}>
        {turn.status === "error" && <ErrorState message={turn.error ?? "Something went wrong."} />}
        {turn.notFound && turn.answer !== null ? (
          <div className="flex items-start gap-3 rounded-[var(--radius-md)] bg-[var(--color-surface-2)] p-3 text-sm">
            <SearchX aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-medium">Not found in your documents.</p>
              <p className="text-[var(--color-muted)]">CORTEX only answers from your library. Try rephrasing, or upload a document that covers this.</p>
            </div>
          </div>
        ) : text ? (
          <Markdown text={text} onCite={onCite} maxCitation={turn.evidence.length || undefined} />
        ) : running ? (
          <p className="text-sm text-[var(--color-muted)]">{turn.steps.at(-1)?.action ?? "Starting"}…</p>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2" onClick={(e) => e.stopPropagation()}>
        {running ? (
          <Button size="sm" variant="secondary" onClick={onStop}><Square aria-hidden className="h-3.5 w-3.5" /> Stop</Button>
        ) : (
          <>
            {text && !turn.notFound && (
              <Button size="sm" variant="ghost" onClick={copy} aria-label="Copy answer">
                {copied ? <Check aria-hidden className="h-4 w-4" /> : <Copy aria-hidden className="h-4 w-4" />}
              </Button>
            )}
            {turn.status === "done" && (
              <>
                <Button size="sm" variant="ghost" aria-pressed={turn.feedback === 1} aria-label="Helpful" onClick={() => onRate(1)}>
                  <ThumbsUp aria-hidden className={`h-4 w-4 ${turn.feedback === 1 ? "text-[var(--color-success)]" : ""}`} />
                </Button>
                <Button size="sm" variant="ghost" aria-pressed={turn.feedback === -1} aria-label="Not helpful" onClick={() => onRate(-1)}>
                  <ThumbsDown aria-hidden className={`h-4 w-4 ${turn.feedback === -1 ? "text-[var(--color-danger)]" : ""}`} />
                </Button>
              </>
            )}
          </>
        )}
        {turn.evidence.length > 0 && (
          <div className="ml-auto flex flex-wrap gap-1" aria-label="Sources">
            {turn.evidence.map((e) => (
              <button key={e.chunk_id} onClick={() => onCite(e.n)} title={`${e.title} — ${e.heading}`}
                className="max-w-48 truncate rounded-full border border-[var(--color-border)] px-2 py-0.5 text-xs hover:border-[var(--color-accent)]">
                [{e.n}] {e.title}
              </button>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
