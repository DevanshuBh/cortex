"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { api, data, uploadToPresignedUrl, type Document } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { describeError } from "@/lib/errors";
import { ACCEPT, mimeOf, validateFile } from "@/lib/upload";

const PROCESSING = new Set(["pending_upload", "uploaded", "parsing", "embedding", "extracting"]);

const STATUS_TONE: Record<string, "neutral" | "accent" | "success" | "warning" | "danger"> = {
  pending_upload: "neutral", uploaded: "accent", parsing: "accent", embedding: "accent", extracting: "accent",
  ready: "success", failed: "danger",
};

interface UploadItem {
  key: string;
  file: File;
  progress: number;
  state: "uploading" | "queued" | "error";
  error?: string;
}

export default function LibraryPage() {
  const { session } = useAuth();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [confirm, setConfirm] = useState<Document | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const docs = useQuery({
    queryKey: ["documents", query],
    queryFn: async () => data(await api.GET("/v1/documents", { params: { query: { q: query || undefined, limit: 200 } } })),
    // Status updates without refreshing: poll while anything is still being processed.
    refetchInterval: (q) => (q.state.data?.items.some((d) => PROCESSING.has(d.status)) || uploads.some((u) => u.state === "uploading") ? 2000 : false),
  });

  const remove = useMutation({
    mutationFn: async (id: string) => data(await api.DELETE("/v1/documents/{document_id}", { params: { path: { document_id: id } } })),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ["documents"] });
      const previous = qc.getQueryData(["documents", query]);
      qc.setQueryData(["documents", query], (old: typeof docs.data) => old && { ...old, items: old.items.filter((d) => d.id !== id), total: old.total - 1 });
      return { previous };
    },
    onError: (_e, _id, ctx) => ctx && qc.setQueryData(["documents", query], ctx.previous), // optimistic rollback
    onSettled: () => qc.invalidateQueries({ queryKey: ["documents"] }),
  });

  const setItem = (key: string, patch: Partial<UploadItem>) =>
    setUploads((us) => us.map((u) => (u.key === key ? { ...u, ...patch } : u)));

  const uploadOne = async (item: UploadItem) => {
    setItem(item.key, { state: "uploading", progress: 0, error: undefined });
    try {
      const mime = mimeOf(item.file);
      const created = data(await api.POST("/v1/documents", { body: { filename: item.file.name, content_type: mime, size_bytes: item.file.size } }));
      await uploadToPresignedUrl(created.upload_url, item.file, created.upload_headers, (p) => setItem(item.key, { progress: p }));
      data(await api.POST("/v1/documents/{document_id}/complete", { params: { path: { document_id: created.document_id } } }));
      setItem(item.key, { state: "queued", progress: 1 });
      void qc.invalidateQueries({ queryKey: ["documents"] });
      setTimeout(() => setUploads((us) => us.filter((u) => u.key !== item.key)), 2500);
    } catch (e) {
      setItem(item.key, { state: "error", error: describeError(e) });
    }
  };

  const addFiles = (files: FileList | File[]) => {
    const items: UploadItem[] = [];
    for (const file of Array.from(files)) {
      const err = validateFile(file);
      const item: UploadItem = { key: crypto.randomUUID(), file, progress: 0, state: err ? "error" : "uploading", error: err ?? undefined };
      items.push(item);
    }
    setUploads((us) => [...us, ...items]);
    items.filter((i) => !i.error).forEach((i) => void uploadOne(i)); // parallel uploads
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Library</h1>
          <p className="text-sm text-[var(--color-muted)]">Documents your team can ask questions about.</p>
        </div>
        <div className="flex gap-2">
          <label htmlFor="doc-search" className="sr-only">Search by title</label>
          <input id="doc-search" type="search" placeholder="Search by title" value={query} onChange={(e) => setQuery(e.target.value)}
            className="h-10 w-56 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 text-sm" />
          <Button variant="primary" onClick={() => inputRef.current?.click()}><Upload aria-hidden className="h-4 w-4" /> Upload</Button>
          <input ref={inputRef} type="file" multiple accept={ACCEPT.join(",")} className="sr-only" aria-label="Choose files to upload"
            onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }} />
        </div>
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
        className={`rounded-[var(--radius-lg)] border-2 border-dashed p-6 text-center text-sm ${dragging ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]" : "border-[var(--color-border)] text-[var(--color-muted)]"}`}
      >
        Drop PDF, Markdown, HTML or text files here (up to 25 MB each).
      </div>

      {uploads.length > 0 && (
        <Card className="divide-y divide-[var(--color-border)]">
          {uploads.map((u) => (
            <div key={u.key} className="flex items-center gap-3 px-4 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate">{u.file.name}</span>
              {u.state === "error" ? (
                <>
                  <span role="alert" className="text-[var(--color-danger)]">{u.error}</span>
                  {!validateFile(u.file) && <Button size="sm" onClick={() => void uploadOne(u)}>Retry</Button>}
                  <Button size="sm" variant="ghost" aria-label="Dismiss" onClick={() => setUploads((us) => us.filter((x) => x.key !== u.key))}><X aria-hidden className="h-4 w-4" /></Button>
                </>
              ) : (
                <div className="flex w-48 items-center gap-2">
                  <progress className="h-1.5 flex-1 accent-[var(--color-accent)]" value={u.progress} max={1} aria-label={`Upload progress for ${u.file.name}`} />
                  <span className="w-16 text-right text-xs text-[var(--color-muted)]">{u.state === "queued" ? "queued" : `${Math.round(u.progress * 100)}%`}</span>
                </div>
              )}
            </div>
          ))}
        </Card>
      )}

      {remove.isError && <ErrorState message={describeError(remove.error)} />}
      {docs.isPending ? (
        <Card className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}</Card>
      ) : docs.isError ? (
        <ErrorState message={describeError(docs.error)} onRetry={() => docs.refetch()} />
      ) : docs.data.items.length === 0 ? (
        <Card>
          <EmptyState title={query ? "No documents match" : "No documents yet"}>
            {query ? "Try a different title." : "Upload your team's documentation, runbooks or reports. Each one is split into passages, indexed for search, and mined for a knowledge graph."}
          </EmptyState>
        </Card>
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Documents ({docs.data.total})</caption>
            <thead className="text-xs text-[var(--color-muted)]">
              <tr><th className="px-4 py-2">Title</th><th className="px-4 py-2">Status</th><th className="px-4 py-2 text-right">Passages</th><th className="px-4 py-2">Added</th><th className="px-4 py-2"><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody>
              {docs.data.items.map((d) => (
                <tr key={d.id} className="border-t border-[var(--color-border)]">
                  <td className="max-w-md px-4 py-2"><div className="truncate font-medium">{d.title}</div><div className="truncate text-xs text-[var(--color-muted)]">{d.filename}</div></td>
                  <td className="px-4 py-2">
                    <Badge tone={STATUS_TONE[d.status] ?? "neutral"}>{d.status.replace("_", " ")}</Badge>
                    {d.error && <div className="mt-1 max-w-xs text-xs text-[var(--color-danger)]">{d.error}</div>}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{d.chunk_count}</td>
                  <td className="whitespace-nowrap px-4 py-2 text-[var(--color-muted)]">{new Date(d.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-2 text-right">
                    {session?.isAdmin && (
                      <Button size="sm" variant="ghost" aria-label={`Delete ${d.title}`} onClick={() => setConfirm(d)}><Trash2 aria-hidden className="h-4 w-4" /></Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {confirm && (
        <div role="dialog" aria-modal="true" aria-labelledby="del-title" className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"
          onKeyDown={(e) => e.key === "Escape" && setConfirm(null)}>
          <Card className="w-full max-w-md p-5">
            <h2 id="del-title" className="text-lg font-semibold">Delete “{confirm.title}”?</h2>
            <p className="mt-2 text-sm text-[var(--color-muted)]">
              Its passages, search index entries and knowledge-graph facts are removed. It will no longer appear in any answer.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button autoFocus onClick={() => setConfirm(null)}>Cancel</Button>
              <Button variant="danger" onClick={() => { remove.mutate(confirm.id); setConfirm(null); }}>Delete</Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
