"use client";

import Link from "next/link";
import { Card } from "@/components/ui";
import { config } from "@/lib/config";
import { isRecorded, recordedAt, recordedModels } from "@/mocks/scenarios";

const PIPELINE = [
  ["Ingest", "Documents go straight from the browser to S3-compatible storage. A worker parses them, splits them into passages of up to 400 tokens and embeds them (bge-small, 384 dimensions) into Postgres + pgvector."],
  ["Retrieve", "Postgres full-text search and pgvector HNSW run side by side, are fused with Reciprocal Rank Fusion, then re-ordered by a cross-encoder."],
  ["Relate", "A small local model extracts entities and relations into a per-tenant Neo4j graph. Relationship questions walk bounded paths and cite the passage behind every edge."],
  ["Answer", "A LangGraph supervisor routes the question, a Researcher gathers evidence, a Coder runs calculations in a network-less sandbox and an Analyst writes the answer. Step, token and time budgets guarantee every run ends."],
  ["Check", "A grounding gate drops citations that don't match retrieved passages; an answer with no valid citation becomes “Not found in your documents.”"],
];

const RESULTS = [
  ["Dense only (pgvector)", "36.8 %", "93.0 % [86.0, 98.2]", "0.583"],
  ["Full-text only", "17.5 %", "48.2 % [36.0, 61.4]", "0.279"],
  ["Fused (RRF)", "33.3 %", "86.8 % [78.1, 94.7]", "0.482"],
  ["Fused + cross-encoder", "52.6 %", "95.6 % [89.5, 100]", "0.693"],
];

const STACK = [
  ["Back end", "Python 3.13, FastAPI, Celery, Redis Streams (resumable SSE), LangGraph"],
  ["Data", "PostgreSQL 18 + pgvector with forced row-level security, Neo4j, S3 (SeaweedFS)"],
  ["Models", "Open-weight models through Ollama on a laptop GPU, one client for Ollama, OpenAI-compatible APIs and Bedrock"],
  ["Front end", "Next.js 16, React 19, Tailwind 4, TanStack Query, Cytoscape, Playwright + axe"],
  ["Operations", "Keycloak (OIDC), Prometheus, Grafana, Jaeger, k3s manifests, Terraform for Oracle Cloud and AWS"],
];

export default function AboutPage() {
  return (
    <article className="mx-auto max-w-3xl space-y-6 pb-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">About CORTEX</h1>
        <p className="mt-2 text-[var(--color-muted)]">
          A multi-tenant research assistant that answers questions over a team&apos;s documents and cites the exact passage
          behind every claim — measured on a labelled evaluation set, with confidence intervals on every number.
        </p>
      </header>

      {config.demo && (
        <Card>
          <h2 className="font-semibold">About this demo</h2>
          <p className="mt-2 text-sm">
            GitHub Pages serves static files only, so this page has no model server behind it. A service worker answers
            the app&apos;s API calls instead.{" "}
            {isRecorded ? (
              <>
                The answers are real: they were recorded from the full system
                {recordedModels ? <> ({recordedModels.small} and {recordedModels.large}, running locally)</> : null}
                {recordedAt ? <> on {recordedAt.slice(0, 10)}</> : null}, including every agent step, retrieved passage
                and graph path, and are replayed at a faster pace.
              </>
            ) : (
              <>The sample answer shows the exact shape of the system&apos;s output.</>
            )}{" "}
            Everything else — streaming, citations, the source viewer, the graph explorer, the library and the dashboard —
            is the same front end that runs against the live API.
          </p>
        </Card>
      )}

      <section aria-labelledby="how">
        <h2 id="how" className="mb-3 text-lg font-semibold">How it works</h2>
        <ol className="space-y-3">
          {PIPELINE.map(([name, text], i) => (
            <li key={name} className="flex gap-3">
              <span aria-hidden className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[var(--color-accent-soft)] text-xs font-semibold text-[var(--color-accent)]">{i + 1}</span>
              <p className="text-sm"><strong>{name}.</strong> {text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="results">
        <h2 id="results" className="mb-1 text-lg font-semibold">Measured retrieval quality</h2>
        <p className="mb-3 text-sm text-[var(--color-muted)]">
          57 hand-labelled questions over 347 Kubernetes documentation pages; 95 % bootstrap intervals.
        </p>
        <div className="overflow-x-auto rounded-[var(--radius-lg)] border border-[var(--color-border)]">
          <table className="w-full text-sm">
            <thead className="bg-[var(--color-surface-2)] text-left">
              <tr><th className="p-2 font-medium">Retrieval</th><th className="p-2 font-medium">Recall@1</th><th className="p-2 font-medium">Recall@10</th><th className="p-2 font-medium">MRR</th></tr>
            </thead>
            <tbody>
              {RESULTS.map(([name, r1, r10, mrr]) => (
                <tr key={name} className="border-t border-[var(--color-border)]">
                  <td className="p-2">{name}</td><td className="p-2 tabular-nums">{r1}</td><td className="p-2 tabular-nums">{r10}</td><td className="p-2 tabular-nums">{mrr}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-sm">
          The cross-encoder lifts the top result by 15.8 points; at Recall@10 its gain over dense retrieval is within noise
          at this sample size, and is reported that way.
        </p>
      </section>

      <section aria-labelledby="eng">
        <h2 id="eng" className="mb-3 text-lg font-semibold">Engineering</h2>
        <ul className="list-disc space-y-1.5 pl-5 text-sm">
          <li>Tenant isolation is enforced three ways — token-derived tenant, query filters, forced Postgres row-level security — and tested against the classic mistakes.</li>
          <li>Filtered vector search stays correct for small tenants (HNSW iterative scan, verified against exact search).</li>
          <li>Answers stream over Server-Sent Events and resume after a dropped connection without losing tokens.</li>
          <li>Generated code runs in a throwaway container with no network, a read-only filesystem and no capabilities; 11 escape tests must fail safely.</li>
          <li>95 back-end tests against real Postgres, Redis and Neo4j; end-to-end journeys on desktop and phone with zero WCAG 2.2 AA violations.</li>
        </ul>
      </section>

      <section aria-labelledby="stack">
        <h2 id="stack" className="mb-3 text-lg font-semibold">Stack</h2>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[8rem_1fr]">
          {STACK.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="font-medium">{k}</dt>
              <dd className="text-[var(--color-muted)]">{v}</dd>
            </div>
          ))}
        </dl>
      </section>

      <p className="flex flex-wrap gap-4 text-sm">
        <Link href="/" className="font-medium text-[var(--color-accent)] underline underline-offset-2">Try the demo</Link>
        {config.repoUrl && (
          <a href={config.repoUrl} className="font-medium text-[var(--color-accent)] underline underline-offset-2">Source code, design doc and benchmarks</a>
        )}
      </p>
    </article>
  );
}
