"use client";

import type cytoscape from "cytoscape";
import { useEffect, useRef, useState } from "react";
import type { EvidenceItem, GraphPath } from "@/lib/api";
import { Button } from "./ui";

/**
 * Entity paths behind a relationship answer. Clicking a node or edge opens the passage it came from.
 * A table view of the same data serves keyboard and screen-reader users.
 */
export function GraphView({ paths, evidence, onOpen }: { paths: GraphPath[]; evidence: EvidenceItem[]; onOpen: (n: number) => void }) {
  const [mode, setMode] = useState<"graph" | "table">("graph");
  const ref = useRef<HTMLDivElement>(null);
  const nByChunk = new Map(evidence.map((e) => [e.chunk_id, e.n]));

  useEffect(() => {
    if (mode !== "graph" || !ref.current || !paths.length) return;
    let cy: cytoscape.Core | undefined;
    let cancelled = false;
    import("cytoscape").then(({ default: cytoscapeLib }) => {
      if (cancelled || !ref.current) return;
      const nodes = new Map<string, { id: string; label: string }>();
      const edges: { id: string; source: string; target: string; label: string; cite: number | null }[] = [];
      for (const p of paths) {
        p.nodes.forEach((n) => nodes.set(n, { id: n, label: n }));
        p.relations.forEach((rel, i) => {
          const reverse = rel.endsWith("(reverse)");
          const a = p.nodes[i]!, b = p.nodes[i + 1]!;
          const cite = p.chunk_ids.map((c) => nByChunk.get(c)).find((n) => n !== undefined) ?? null;
          edges.push({ id: `${a}-${rel}-${b}-${edges.length}`, source: reverse ? b : a, target: reverse ? a : b,
                       label: rel.replace(" (reverse)", ""), cite });
        });
      }
      const css = getComputedStyle(document.documentElement);
      const color = (v: string) => css.getPropertyValue(v).trim() || "#888";
      cy = cytoscapeLib({
        container: ref.current,
        elements: [
          ...[...nodes.values()].map((n) => ({ data: n })),
          ...edges.map((e) => ({ data: e })),
        ],
        layout: { name: "cose", animate: false, padding: 20 },
        style: [
          { selector: "node", style: { label: "data(label)", "background-color": color("--color-accent"), color: color("--color-text"),
            "font-size": 11, "text-valign": "bottom", "text-margin-y": 4, width: 18, height: 18 } },
          { selector: "edge", style: { label: "data(label)", "curve-style": "bezier", "target-arrow-shape": "triangle",
            "line-color": color("--color-border"), "target-arrow-color": color("--color-border"), "font-size": 9,
            color: color("--color-muted"), "text-rotation": "autorotate", width: 1.5 } },
        ],
      });
      cy.on("tap", "edge", (ev) => {
        const cite = ev.target.data("cite") as number | null;
        if (cite) onOpen(cite);
      });
      cy.on("tap", "node", (ev) => {
        const name = ev.target.id() as string;
        const path = paths.find((p) => p.nodes.includes(name));
        const cite = path?.chunk_ids.map((c) => nByChunk.get(c)).find((n) => n !== undefined);
        if (cite) onOpen(cite);
      });
    });
    return () => {
      cancelled = true;
      cy?.destroy();
    };
  }, [mode, paths, evidence]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!paths.length) return <p className="text-sm text-[var(--color-muted)]">This answer did not use the knowledge graph.</p>;
  return (
    <section aria-label="Knowledge graph paths" className="space-y-2">
      <div className="flex gap-1" role="tablist">
        <Button size="sm" variant={mode === "graph" ? "primary" : "ghost"} role="tab" aria-selected={mode === "graph"} onClick={() => setMode("graph")}>Graph</Button>
        <Button size="sm" variant={mode === "table" ? "primary" : "ghost"} role="tab" aria-selected={mode === "table"} onClick={() => setMode("table")}>Table</Button>
      </div>
      {mode === "graph" ? (
        <div ref={ref} className="h-80 w-full rounded-[var(--radius-md)] border border-[var(--color-border)]" aria-hidden />
      ) : (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Relationship paths and their sources</caption>
          <thead className="text-xs text-[var(--color-muted)]"><tr><th className="py-1">Path</th><th>Sources</th></tr></thead>
          <tbody>
            {paths.map((p, i) => (
              <tr key={i} className="border-t border-[var(--color-border)]">
                <td className="py-1.5 pr-2">{p.text}</td>
                <td className="whitespace-nowrap">
                  {p.chunk_ids.map((c) => nByChunk.get(c)).filter((n): n is number => n !== undefined).map((n) => (
                    <button key={n} className="mr-1 inline-flex min-h-6 min-w-6 items-center justify-center text-[var(--color-accent)] underline" onClick={() => onOpen(n)}>[{n}]</button>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
