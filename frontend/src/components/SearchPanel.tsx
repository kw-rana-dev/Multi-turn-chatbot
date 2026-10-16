"use client";

import { useCallback, useState } from "react";
import { semanticSearch, citationToTarget, type Chunk, type PreviewTarget } from "@/lib/api";
import DocumentPreview from "./DocumentPreview";
import styles from "./SearchPanel.module.css";

export default function SearchPanel() {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [results, setResults] = useState<Chunk[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<(PreviewTarget & { chunkId: string }) | null>(null);
  const closePreview = useCallback(() => setPreview(null), []);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setSearched(true);
    setError(null);
    try {
      const res = await semanticSearch(query, topK);
      setResults(res.chunks);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.layout}>
      <div className={styles.wrap}>
        <div className={styles.header}>
          <h1 className="gradient-text">Semantic Search</h1>
          <p className={styles.subtitle}>Search your library using vector similarity — click a result to see it in context</p>
        </div>

        <form id="search-form" className={`glass-card ${styles.searchCard}`} onSubmit={handleSearch}>
          <div className={styles.searchRow}>
            <input
              id="search-input"
              className={`input ${styles.searchInput}`}
              placeholder="What would you like to find?"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button id="btn-search" type="submit" className="btn btn-primary" disabled={loading || !query.trim()}>
              {loading ? <span className="spinner" /> : "🔍 Search"}
            </button>
          </div>
          <div className={styles.searchOptions}>
            <label className={styles.optionLabel}>
              Top K results:
              <select id="select-topk" className={styles.select} value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
                {[3, 5, 8, 10, 15, 20].map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </form>

        {loading && (
          <div className={styles.loadingState}>
            <span className="spinner" /> Searching with pgvector…
          </div>
        )}

        {error && <div className={styles.emptyState}>{error}</div>}

        {!loading && !error && searched && results.length === 0 && (
          <div className={styles.emptyState}>
            <span style={{ fontSize: "2.5rem" }}>🔎</span>
            <p>No results found. Try uploading some documents first!</p>
          </div>
        )}

        {!loading && results.length > 0 && (
          <div className={styles.results}>
            <p className={styles.resultsLabel}>
              {results.length} result{results.length !== 1 ? "s" : ""} for &quot;{query}&quot;
            </p>
            {results.map((chunk, i) => (
              <button
                key={chunk.id}
                type="button"
                className={`glass-card ${styles.resultCard} ${preview?.chunkId === chunk.id ? styles.resultCardActive : ""} animate-fade-in`}
                style={{ animationDelay: `${i * 0.05}s` }}
                onClick={() => setPreview({ ...citationToTarget(chunk, `#${i + 1}`), chunkId: chunk.id })}
              >
                <div className={styles.resultHeader}>
                  <span className={styles.resultTitle}>{chunk.document_title ?? "Untitled"}</span>
                  <span className={styles.resultPage}>
                    {chunk.page ? `Page ${chunk.page} · ` : ""}Chunk #{chunk.chunk_index + 1}
                  </span>
                  {chunk.score !== null && (
                    <div className={styles.scoreBar}>
                      <div className={styles.scoreBarFill} style={{ width: `${Math.max(0, chunk.score * 100).toFixed(0)}%` }} />
                      <span className={styles.scoreLabel}>{(chunk.score * 100).toFixed(1)}% match</span>
                    </div>
                  )}
                </div>
                <p className={styles.resultContent}>{chunk.content}</p>
              </button>
            ))}
          </div>
        )}
      </div>

      {preview && <DocumentPreview target={preview} onClose={closePreview} />}
    </div>
  );
}
