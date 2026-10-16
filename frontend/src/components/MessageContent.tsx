"use client";

import { useMemo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "@/lib/api";
import styles from "./MessageContent.module.css";

/** Legacy messages stored sources without `n`; their position is the number. */
export function numberedSources(sources: Citation[]): Array<Citation & { n: number }> {
  return sources.map((s, i) => ({ ...s, n: s.n ?? i + 1 }));
}

/** Turn [1] / [1, 3] markers into markdown links react-markdown hands to our `a` renderer. */
function linkCitations(markdown: string) {
  return markdown.replace(/\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\()/g, (_, nums: string) =>
    nums
      .split(/\s*,\s*/)
      .map((n) => `[${n}](#cite-${n})`)
      .join("")
  );
}

export default function MessageContent({
  content,
  sources,
  activeKey,
  onCite,
}: {
  content: string;
  sources: Citation[];
  activeKey?: string | null;
  onCite: (source: Citation & { n: number }) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const numbered = useMemo(() => numberedSources(sources), [sources]);
  const byNumber = useMemo(() => new Map(numbered.map((s) => [s.n, s])), [numbered]);

  const components = useMemo<Components>(
    () => ({
      a({ href, children }) {
        if (href?.startsWith("#cite-")) {
          const n = Number(href.slice(6));
          const src = byNumber.get(n);
          if (!src) return <span className={styles.citeMissing}>[{n}]</span>;
          return (
            <button
              type="button"
              className={`${styles.cite} ${activeKey === `${src.id}` ? styles.citeActive : ""}`}
              onClick={() => onCite(src)}
              title={`${src.document_title ?? "Source"}${src.page ? ` · p. ${src.page}` : ""}`}
            >
              {n}
            </button>
          );
        }
        return (
          <a href={href} target="_blank" rel="noreferrer">
            {children}
          </a>
        );
      },
    }),
    [byNumber, onCite, activeKey]
  );

  // Show cited sources first; uncited retrievals are tucked behind a toggle
  const hasCitedFlags = numbered.some((s) => s.cited !== undefined);
  const primary = hasCitedFlags ? numbered.filter((s) => s.cited) : numbered;
  const secondary = hasCitedFlags ? numbered.filter((s) => !s.cited) : [];
  const visible = showAll ? [...primary, ...secondary] : primary;

  return (
    <div className={styles.wrap}>
      <div className={styles.markdown}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {linkCitations(content)}
        </ReactMarkdown>
      </div>

      {numbered.length > 0 && (
        <div className={styles.sources}>
          {visible.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`${styles.sourceChip} ${activeKey === s.id ? styles.sourceChipActive : ""}`}
              onClick={() => onCite(s)}
              title={s.content.slice(0, 280)}
            >
              <span className={styles.sourceNum}>{s.n}</span>
              <span className={styles.sourceTitle}>{s.document_title ?? `Chunk #${s.chunk_index + 1}`}</span>
              {s.page != null && <span className={styles.sourcePage}>p. {s.page}</span>}
            </button>
          ))}
          {secondary.length > 0 && (
            <button type="button" className={styles.moreBtn} onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show cited only" : `+${secondary.length} more retrieved`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
