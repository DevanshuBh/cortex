"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import dynamic from "next/dynamic";
import { api, data, type EvidenceItem } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { ErrorState, Skeleton } from "./ui";

const PdfPage = dynamic(() => import("./PdfPage"), { ssr: false, loading: () => <Skeleton className="h-96 w-full" /> });

/** Opens the cited passage: the PDF page with the passage highlighted, or the text chunk in context. */
export function SourcePanel({ evidence }: { evidence: EvidenceItem }) {
  const chunk = useQuery({
    queryKey: ["chunk", evidence.chunk_id],
    queryFn: async () => data(await api.GET("/v1/chunks/{chunk_id}", { params: { path: { chunk_id: evidence.chunk_id } } })),
  });
  if (chunk.isPending) return <Skeleton className="h-48 w-full" />;
  if (chunk.isError) return <ErrorState message={describeError(chunk.error)} onRetry={() => chunk.refetch()} />;
  const c = chunk.data;
  return (
    <article aria-label={`Source ${evidence.n}`} className="space-y-3">
      <header>
        <div className="flex items-center gap-2 text-sm font-medium">
          <FileText aria-hidden className="h-4 w-4" />
          <span>[{evidence.n}] {c.document_title}</span>
        </div>
        <p className="mt-0.5 text-xs text-[var(--color-muted)]">{c.heading_path}{c.page ? ` · page ${c.page}` : ""}</p>
      </header>
      {c.mime === "application/pdf" && c.page ? (
        <PdfPage documentId={c.document_id} page={c.page} highlight={c.text} />
      ) : (
        <blockquote className="whitespace-pre-wrap rounded-[var(--radius-md)] border-l-4 border-[var(--color-accent)] bg-[var(--color-highlight)]/40 p-3 text-sm leading-relaxed">
          {c.text}
        </blockquote>
      )}
    </article>
  );
}
