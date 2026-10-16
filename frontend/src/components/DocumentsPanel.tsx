"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  listDocuments,
  uploadDocument,
  uploadFile,
  deleteDocument,
  reindexDocument,
  documentFileUrl,
  formatBytes,
  fileKind,
  ACCEPTED_FILE_TYPES,
  type Document,
  type PreviewTarget,
} from "@/lib/api";
import DocumentPreview, { invalidatePreviewCache } from "./DocumentPreview";
import styles from "./DocumentsPanel.module.css";

type Filter = "library" | "chat" | "all";

const FILTER_LABELS: Record<Filter, string> = {
  library: "Library",
  chat: "Chat attachments",
  all: "All",
};

export default function DocumentsPanel() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [filter, setFilter] = useState<Filter>("library");
  const [query, setQuery] = useState("");
  const [loadedFilter, setLoadedFilter] = useState<Filter | null>(null);
  const loading = loadedFilter !== filter;
  const [uploading, setUploading] = useState(0);
  const [notice, setNotice] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ title: "", content: "", source: "" });
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState<PreviewTarget | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDocs = useCallback(async (f: Filter) => {
    try {
      setDocuments(await listDocuments(f));
    } catch (e) {
      setNotice({ kind: "error", text: (e as Error).message });
    } finally {
      setLoadedFilter(f);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    listDocuments(filter)
      .then((docs) => !cancelled && setDocuments(docs))
      .catch((e) => !cancelled && setNotice({ kind: "error", text: e.message }))
      .finally(() => !cancelled && setLoadedFilter(filter));
    return () => {
      cancelled = true;
    };
  }, [filter]);

  // Poll while anything is still being indexed
  const processing = documents.some((d) => d.status === "processing");
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(() => loadDocs(filter), 2000);
    return () => clearInterval(t);
  }, [processing, filter, loadDocs]);

  const closePreview = useCallback(() => setPreview(null), []);

  async function handleTextUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title || !form.content) return;
    setUploading((n) => n + 1);
    try {
      await uploadDocument(form);
      setForm({ title: "", content: "", source: "" });
      setShowForm(false);
      await loadDocs(filter);
    } catch (e) {
      setNotice({ kind: "error", text: (e as Error).message });
    } finally {
      setUploading((n) => n - 1);
    }
  }

  async function handleFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    setNotice(null);
    setUploading((n) => n + list.length);
    const duplicates: string[] = [];
    await Promise.all(
      list.map(async (file) => {
        try {
          const doc = await uploadFile(file);
          if (doc.duplicate) duplicates.push(`${file.name} (already uploaded as “${doc.title}”)`);
        } catch (e) {
          setNotice({ kind: "error", text: `${file.name}: ${(e as Error).message}` });
        } finally {
          setUploading((n) => n - 1);
        }
      })
    );
    if (duplicates.length) setNotice({ kind: "info", text: `Skipped duplicates: ${duplicates.join(", ")}` });
    if (filter === "chat") setFilter("library");
    else await loadDocs(filter);
  }

  async function handleReindex(doc: Document) {
    try {
      const updated = await reindexDocument(doc.id);
      invalidatePreviewCache(doc.id);
      setDocuments((prev) => prev.map((d) => (d.id === doc.id ? updated : d)));
    } catch (e) {
      setNotice({ kind: "error", text: (e as Error).message });
    }
  }

  async function handleDelete(doc: Document) {
    if (!confirm(`Delete “${doc.title}”? This removes the file, its chunks, and detaches it from every conversation.`)) return;
    try {
      await deleteDocument(doc.id);
      invalidatePreviewCache(doc.id);
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id));
      if (preview?.documentId === doc.id) setPreview(null);
    } catch (e) {
      setNotice({ kind: "error", text: (e as Error).message });
    }
  }

  const visible = query
    ? documents.filter((d) => `${d.title} ${d.filename ?? ""}`.toLowerCase().includes(query.toLowerCase()))
    : documents;
  const totalSize = documents.reduce((sum, d) => sum + (d.size_bytes ?? 0), 0);
  const totalChunks = documents.reduce((sum, d) => sum + d.chunk_count, 0);

  return (
    <div className={styles.layout}>
      <div className={styles.wrap}>
        <div className={styles.header}>
          <div>
            <h1 className="gradient-text">Knowledge Base</h1>
          </div>
          <div className={styles.headerActions}>
            <button id="btn-add-document" className="btn btn-ghost" onClick={() => setShowForm((v) => !v)}>
              {showForm ? "✕ Cancel" : "+ Paste text"}
            </button>
          </div>
        </div>

        {showForm && (
          <form className={`glass-card ${styles.form} animate-fade-in`} onSubmit={handleTextUpload}>
            <h3>Add Text Document</h3>
            <input id="doc-title" className="input" placeholder="Title *" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required />
            <textarea id="doc-content" className="input" placeholder="Content (paste your text here) *" value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} rows={6} required />
            <input id="doc-source" className="input" placeholder="Source URL or reference (optional)" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} />
            <div className={styles.formActions}>
              <button type="submit" id="btn-submit-doc" className="btn btn-primary" disabled={uploading > 0}>
                Upload &amp; Index
              </button>
            </div>
          </form>
        )}

        <div
          id="file-dropzone"
          className={`${styles.dropzone} ${dragOver ? styles.dropzoneActive : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleFiles(e.dataTransfer.files);
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          {uploading > 0 ? (
            <>
              <span className="spinner" />
              <span>Uploading {uploading} file{uploading > 1 ? "s" : ""}…</span>
            </>
          ) : (
            <>
              <span>
                Drop <strong>PDF, TXT, MD, CSV or JSON</strong> files here, or click to browse
              </span>
            </>
          )}
          <input
            ref={fileInputRef}
            id="file-input"
            type="file"
            multiple
            accept={ACCEPTED_FILE_TYPES}
            hidden
            onChange={(e) => {
              if (e.target.files) handleFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {notice && (
          <div className={notice.kind === "error" ? styles.noticeError : styles.noticeInfo}>
            <span>{notice.text}</span>
            <button onClick={() => setNotice(null)}>✕</button>
          </div>
        )}

        <div className={styles.toolbar}>
          <div className={styles.tabs}>
            {(Object.keys(FILTER_LABELS) as Filter[]).map((f) => (
              <button key={f} className={filter === f ? styles.tabActive : ""} onClick={() => setFilter(f)}>
                {FILTER_LABELS[f]}
              </button>
            ))}
          </div>
          <input className={`input ${styles.search}`} placeholder="Filter by name…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>

        <div className={styles.list}>
          {loading ? (
            <div className={styles.loadingState}>
              <span className="spinner" /> Loading documents…
            </div>
          ) : visible.length === 0 ? (
            <div className={styles.emptyState}>
              <span style={{ fontSize: "2.5rem" }}>📭</span>
              <p>
                {documents.length
                  ? "No documents match this filter."
                  : filter === "chat"
                  ? "No chat attachments yet. Attach files from inside a conversation."
                  : "No documents yet. Upload some content to get started!"}
              </p>
            </div>
          ) : (
            visible.map((doc) => (
              <div
                key={doc.id}
                className={`glass-card ${styles.docCard} ${preview?.documentId === doc.id ? styles.docCardActive : ""} animate-fade-in`}
              >
                <div className={styles.docIcon}>{fileKind(doc)}</div>
                <div className={styles.docInfo}>
                  <div className={styles.docTitleRow}>
                    <button className={styles.docTitle} onClick={() => setPreview({ documentId: doc.id, title: doc.title })} disabled={doc.status === "processing"}>
                      {doc.title}
                    </button>
                    <StatusBadge doc={doc} />
                    {doc.origin === "chat" && <span className="badge badge-blue">chat</span>}
                  </div>
                  <div className={styles.docMeta}>
                    {doc.filename && <span>{doc.filename}</span>}
                    <span>{formatBytes(doc.size_bytes)}</span>
                    {doc.page_count != null && <span>{doc.page_count} page{doc.page_count !== 1 ? "s" : ""}</span>}
                    <span>{doc.chunk_count} chunk{doc.chunk_count !== 1 ? "s" : ""}</span>
                    <span>{new Date(doc.created_at).toLocaleDateString()}</span>
                    {doc.source && doc.source !== doc.filename && <span className={styles.docSource}>🔗 {doc.source}</span>}
                  </div>
                  {doc.status === "failed" && doc.error && <p className={styles.docError}>{doc.error}</p>}
                  {doc.status === "ready" && doc.preview && <p className={styles.docPreview}>{doc.preview}</p>}
                </div>
                <div className={styles.actions}>
                  <button className="btn btn-ghost" title="Preview" onClick={() => setPreview({ documentId: doc.id, title: doc.title })} disabled={doc.status === "processing"}>
                    👁
                  </button>
                  {doc.has_file && (
                    <a className="btn btn-ghost" title="Download original" href={documentFileUrl(doc.id, true)}>
                      ⬇
                    </a>
                  )}
                  <button className="btn btn-ghost" title="Re-index (re-extract, re-chunk, re-embed)" onClick={() => handleReindex(doc)} disabled={doc.status === "processing"}>
                    ↻
                  </button>
                  <button id={`btn-delete-${doc.id.slice(0, 8)}`} className="btn btn-danger" title="Delete" onClick={() => handleDelete(doc)}>
                    🗑
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {preview && <DocumentPreview target={preview} onClose={closePreview} />}
    </div>
  );
}

function StatusBadge({ doc }: { doc: Document }) {
  if (doc.status === "processing")
    return (
      <span className={`badge ${styles.badgeProcessing}`}>
        <span className={styles.miniSpinner} /> indexing
      </span>
    );
  if (doc.status === "failed") return <span className={`badge ${styles.badgeFailed}`}>failed</span>;
  return <span className="badge badge-green">ready</span>;
}
