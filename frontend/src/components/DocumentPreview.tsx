"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  getDocumentContent,
  documentFileUrl,
  type DocumentContent,
  type PreviewTarget,
} from "@/lib/api";
import styles from "./DocumentPreview.module.css";

// Fetched text is cached per document so hopping between citations is instant.
const contentCache = new Map<string, Promise<DocumentContent>>();

function loadContent(id: string) {
  let p = contentCache.get(id);
  if (!p) {
    p = getDocumentContent(id);
    p.catch(() => contentCache.delete(id));
    contentCache.set(id, p);
  }
  return p;
}

export function invalidatePreviewCache(id: string) {
  contentCache.delete(id);
}

type Segment =
  | { kind: "page"; page: number }
  | { kind: "text"; text: string; highlight: boolean };

/** Find the cited range: exact offsets when stored, otherwise locate the snippet (legacy chunks). */
function resolveRange(content: string, target: PreviewTarget): [number, number] | null {
  if (target.charStart != null && target.charEnd != null && target.charEnd <= content.length) {
    return [target.charStart, target.charEnd];
  }
  const snippet = target.snippet?.trim();
  if (!snippet) return null;
  for (const probe of [snippet, snippet.slice(0, 160), snippet.slice(0, 60)]) {
    const at = content.indexOf(probe);
    if (at !== -1) return [at, at + (probe === snippet ? snippet.length : probe.length)];
  }
  return null;
}

function buildSegments(doc: DocumentContent, range: [number, number] | null): Segment[] {
  const text = doc.content;
  const cuts = new Set<number>([0, text.length]);
  const pageAt = new Map<number, number>();
  doc.pages?.forEach((p) => {
    cuts.add(p.start);
    // Empty pages share a start offset with the next page; show the last page that starts here
    pageAt.set(p.start, p.page);
  });
  if (range) {
    cuts.add(range[0]);
    cuts.add(range[1]);
  }
  const points = [...cuts].filter((c) => c >= 0 && c <= text.length).sort((a, b) => a - b);

  const segments: Segment[] = [];
  for (let i = 0; i < points.length; i++) {
    const start = points[i];
    const page = pageAt.get(start);
    if (page != null) segments.push({ kind: "page", page });
    const end = points[i + 1];
    if (end == null || end === start) continue;
    segments.push({
      kind: "text",
      text: text.slice(start, end),
      highlight: !!range && start >= range[0] && end <= range[1],
    });
  }
  return segments;
}

export default function DocumentPreview({
  target,
  onClose,
}: {
  target: PreviewTarget;
  onClose: () => void;
}) {
  const [loaded, setLoaded] = useState<{ id: string; doc?: DocumentContent; error?: string } | null>(null);
  const [view, setView] = useState<"text" | "original">("text");
  const current = loaded?.id === target.documentId ? loaded : null;
  const doc = current?.doc ?? null;
  const error = current?.error ?? null;
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    const id = target.documentId;
    loadContent(id)
      .then((d) => !cancelled && setLoaded({ id, doc: d }))
      .catch((e) => !cancelled && setLoaded({ id, error: e.message }));
    return () => {
      cancelled = true;
    };
  }, [target.documentId]);

  const range = useMemo(() => (doc ? resolveRange(doc.content, target) : null), [doc, target]);
  const segments = useMemo(() => (doc ? buildSegments(doc, range) : []), [doc, range]);

  // Scroll the highlighted passage (or the cited page) into view
  useEffect(() => {
    if (!doc || view !== "text") return;
    const body = bodyRef.current;
    const el =
      body?.querySelector<HTMLElement>("mark") ??
      (target.page ? body?.querySelector<HTMLElement>(`[data-page="${target.page}"]`) : null);
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    } else {
      bodyRef.current?.scrollTo({ top: 0 });
    }
  }, [doc, segments, target, view]);

  const isPdf = doc?.content_type === "application/pdf";
  const originalSrc = doc?.has_file
    ? `${documentFileUrl(target.documentId)}${isPdf && target.page ? `#page=${target.page}` : ""}`
    : null;

  return (
    <aside className={styles.panel} aria-label="Document preview">
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.titleWrap}>
            <div className={styles.eyebrow}>
              {target.label && <span className={styles.citeLabel}>{target.label}</span>}
              {target.page ? <span>Page {target.page}</span> : <span>Document</span>}
            </div>
            <h3 className={styles.title} title={doc?.title ?? target.title ?? ""}>
              {doc?.title ?? target.title ?? "Loading…"}
            </h3>
          </div>
          <button className={styles.iconBtn} onClick={onClose} aria-label="Close preview" title="Close (Esc)">
            ✕
          </button>
        </div>
        <div className={styles.toolbar}>
          <div className={styles.segmented} role="tablist">
            <button
              role="tab"
              aria-selected={view === "text"}
              className={view === "text" ? styles.segActive : ""}
              onClick={() => setView("text")}
            >
              Text
            </button>
            <button
              role="tab"
              aria-selected={view === "original"}
              className={view === "original" ? styles.segActive : ""}
              onClick={() => setView("original")}
              disabled={!originalSrc}
              title={originalSrc ? "Original file" : "No original file stored"}
            >
              Original
            </button>
          </div>
          {doc?.has_file && (
            <div className={styles.links}>
              <a href={documentFileUrl(target.documentId)} target="_blank" rel="noreferrer">
                Open ↗
              </a>
              <a href={documentFileUrl(target.documentId, true)}>Download</a>
            </div>
          )}
        </div>
      </header>

      {view === "text" ? (
        <div className={styles.body} ref={bodyRef}>
          {error && <div className={styles.error}>Couldn&apos;t load document: {error}</div>}
          {!doc && !error && (
            <>
              {target.snippet && (
                <div className={styles.snippetCard}>
                  <div className={styles.snippetLabel}>Cited passage</div>
                  <p>{target.snippet}</p>
                </div>
              )}
              <div className={styles.skeleton}>
                <span />
                <span />
                <span />
              </div>
            </>
          )}
          {doc && !doc.content && <div className={styles.empty}>No text has been extracted yet.</div>}
          {doc && doc.content && (
            <div className={styles.text}>
              {segments.map((s, i) => {
                if (s.kind === "page") {
                  return (
                    <div key={`p${i}`} className={styles.pageBreak} data-page={s.page}>
                      <span>Page {s.page}</span>
                    </div>
                  );
                }
                return s.highlight ? (
                  <mark key={`t${i}`} className={styles.mark}>
                    {s.text}
                  </mark>
                ) : (
                  <span key={`t${i}`}>{s.text}</span>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        originalSrc && (
          <iframe key={originalSrc} className={styles.frame} src={originalSrc} title={doc?.title ?? "Original file"} />
        )
      )}
    </aside>
  );
}
