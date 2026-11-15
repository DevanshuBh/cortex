"use client";

import { useEffect, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import { tokenStore } from "@/lib/auth";
import { config } from "@/lib/config";
import { ErrorState, Skeleton } from "./ui";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();

function words(s: string): Set<string> {
  return new Set(s.toLowerCase().match(/[a-z0-9]{4,}/g) ?? []);
}

/** One PDF page fetched through the API (tenant-checked), with the cited passage's text spans highlighted. */
export default function PdfPage({ documentId, page, highlight }: { documentId: string; page: number; highlight: string }) {
  const [file, setFile] = useState<Blob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const target = words(highlight);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch(`${config.apiUrl}/v1/documents/${documentId}/file`, {
      headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}` },
      signal: ctrl.signal,
    })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`could not load the PDF (${r.status})`))))
      .then(setFile)
      .catch((e: unknown) => !ctrl.signal.aborted && setError(e instanceof Error ? e.message : "could not load the PDF"));
    return () => ctrl.abort();
  }, [documentId]);

  if (error) return <ErrorState message={error} />;
  if (!file) return <Skeleton className="h-96 w-full" />;
  return (
    <div className="overflow-hidden rounded-[var(--radius-md)] border border-[var(--color-border)]">
      <Document file={file} loading={<Skeleton className="h-96 w-full" />}>
        <Page
          pageNumber={page}
          width={520}
          renderAnnotationLayer={false}
          customTextRenderer={({ str }) => {
            const hit = [...words(str)].some((w) => target.has(w));
            const safe = str.replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
            return hit ? `<mark>${safe}</mark>` : safe;
          }}
        />
      </Document>
    </div>
  );
}
