"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  listConversations,
  createConversation,
  renameConversation,
  deleteConversation,
  getMessages,
  sendMessage,
  getConversationDocuments,
  linkConversationDocuments,
  unlinkConversationDocument,
  attachFile,
  listDocuments,
  citationToTarget,
  fileKind,
  ACCEPTED_FILE_TYPES,
  type Conversation,
  type Message,
  type Document,
  type Citation,
  type PreviewTarget,
} from "@/lib/api";
import MessageContent from "./MessageContent";
import DocumentPreview from "./DocumentPreview";
import styles from "./ChatPanel.module.css";

type ActivePreview = PreviewTarget & { messageId?: string; chunkId?: string };

function relativeTime(iso: string, now: number) {
  const diff = (now - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d`;
  return new Date(iso).toLocaleDateString();
}

export default function ChatPanel() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convFilter, setConvFilter] = useState("");
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [convDocs, setConvDocs] = useState<Document[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ActivePreview | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [libraryDocs, setLibraryDocs] = useState<Document[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  // Conversations created client-side are empty; skip the load so it can't clobber optimistic state
  const freshConvId = useRef<string | null>(null);
  const tempSeq = useRef(0);

  const activeConv = conversations.find((c) => c.id === activeConvId) ?? null;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    listConversations().then(setConversations).catch((e) => setError(e.message));
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!activeConvId) return;
    if (freshConvId.current === activeConvId) {
      freshConvId.current = null;
      return;
    }
    let cancelled = false;
    Promise.all([getMessages(activeConvId), getConversationDocuments(activeConvId)])
      .then(([msgs, docs]) => {
        if (cancelled) return;
        setMessages(msgs);
        setConvDocs(docs);
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [activeConvId]);

  // Poll while attached documents are still being indexed
  const processing = convDocs.some((d) => d.status === "processing");
  useEffect(() => {
    if (!activeConvId || !processing) return;
    const t = setInterval(() => {
      getConversationDocuments(activeConvId).then(setConvDocs).catch(() => {});
    }, 2000);
    return () => clearInterval(t);
  }, [activeConvId, processing]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const closePreview = useCallback(() => setPreview(null), []);

  function selectConversation(id: string) {
    if (id === activeConvId) return;
    setActiveConvId(id);
    setMessages([]);
    setConvDocs([]);
    setPreview(null);
    setPickerOpen(false);
    setError(null);
  }

  function bumpConversation(id: string, patch: Partial<Conversation>) {
    setConversations((prev) => {
      const conv = prev.find((c) => c.id === id);
      if (!conv) return prev;
      return [{ ...conv, ...patch }, ...prev.filter((c) => c.id !== id)];
    });
  }

  async function ensureConversation(): Promise<string> {
    if (activeConvId) return activeConvId;
    const conv = await createConversation();
    freshConvId.current = conv.id;
    setConversations((prev) => [conv, ...prev]);
    setActiveConvId(conv.id);
    setMessages([]);
    setConvDocs([]);
    return conv.id;
  }

  async function handleNewConversation() {
    try {
      const conv = await createConversation();
      freshConvId.current = conv.id;
      setConversations((prev) => [conv, ...prev]);
      selectConversation(conv.id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleDeleteConversation(id: string) {
    if (!confirm("Delete this conversation? Attached documents stay in the Documents tab.")) return;
    try {
      await deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (id === activeConvId) {
        setActiveConvId(null);
        setMessages([]);
        setConvDocs([]);
        setPreview(null);
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function commitRename() {
    const id = editingId;
    const title = editTitle.trim();
    setEditingId(null);
    if (!id || !title) return;
    try {
      const updated = await renameConversation(id, title);
      setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title: updated.title } : c)));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    setError(null);
    let convId: string;
    try {
      convId = await ensureConversation();
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    setUploading((n) => n + list.length);
    await Promise.all(
      list.map(async (file) => {
        try {
          const doc = await attachFile(convId, file);
          setConvDocs((prev) => [...prev.filter((d) => d.id !== doc.id), doc]);
        } catch (e) {
          setError(`${file.name}: ${(e as Error).message}`);
        } finally {
          setUploading((n) => n - 1);
        }
      })
    );
    bumpConversation(convId, {});
  }

  async function openPicker() {
    setPickerOpen((v) => !v);
    try {
      setLibraryDocs(await listDocuments("library"));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function toggleLibraryDoc(doc: Document) {
    try {
      const convId = await ensureConversation();
      if (convDocs.some((d) => d.id === doc.id)) {
        await unlinkConversationDocument(convId, doc.id);
        setConvDocs((prev) => prev.filter((d) => d.id !== doc.id));
      } else {
        setConvDocs(await linkConversationDocuments(convId, [doc.id]));
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleDetach(doc: Document) {
    if (!activeConvId) return;
    try {
      await unlinkConversationDocument(activeConvId, doc.id);
      setConvDocs((prev) => prev.filter((d) => d.id !== doc.id));
      if (preview?.documentId === doc.id) setPreview(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || sending) return;
    setError(null);
    let convId: string;
    try {
      convId = await ensureConversation();
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    setInput("");
    setSending(true);
    const tempId = `temp-${++tempSeq.current}`;
    setMessages((prev) => [
      ...prev,
      { id: tempId, conversation_id: convId, role: "user", content: text, sources: [], created_at: new Date().toISOString() },
    ]);
    try {
      const res = await sendMessage(convId, text);
      setMessages((prev) => [...prev.filter((m) => m.id !== tempId), res.user_message, res.assistant_message]);
      bumpConversation(convId, {
        title: res.conversation_title,
        updated_at: res.assistant_message.created_at,
      });
    } catch (e) {
      setMessages((prev) => prev.filter((m) => m.id !== tempId));
      setInput(text);
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  }

  const openCitation = useCallback((messageId: string, src: Citation & { n: number }) => {
    setPreview({ ...citationToTarget(src, `[${src.n}]`), messageId, chunkId: src.id });
  }, []);

  const filteredConvs = convFilter
    ? conversations.filter((c) => c.title.toLowerCase().includes(convFilter.toLowerCase()))
    : conversations;

  const readyDocs = convDocs.filter((d) => d.status === "ready").length;
  const scopeHint = convDocs.length
    ? `Answers grounded in ${convDocs.length} attached document${convDocs.length > 1 ? "s" : ""}${
        readyDocs < convDocs.length ? ` · ${convDocs.length - readyDocs} indexing` : ""
      }`
    : "No documents attached — searching your whole library";

  return (
    <div className={styles.wrap}>
      {/* ─── Conversation list ─────────────────────────────── */}
      <div className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <span>Conversations</span>
          <button id="btn-new-conversation" className={styles.newBtn} onClick={handleNewConversation} title="New conversation">
            + New
          </button>
        </div>
        <div className={styles.convSearch}>
          <input
            className="input"
            placeholder="Search chats…"
            value={convFilter}
            onChange={(e) => setConvFilter(e.target.value)}
          />
        </div>
        <div className={styles.convList}>
          {filteredConvs.length === 0 && (
            <p className={styles.emptyNote}>{conversations.length ? "No matches" : "No conversations yet"}</p>
          )}
          {filteredConvs.map((c) => (
            <div
              key={c.id}
              className={`${styles.convItem} ${activeConvId === c.id ? styles.convItemActive : ""}`}
              onClick={() => selectConversation(c.id)}
            >
              {editingId === c.id ? (
                <input
                  className={styles.renameInput}
                  autoFocus
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onBlur={commitRename}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitRename();
                    if (e.key === "Escape") setEditingId(null);
                  }}
                />
              ) : (
                <>
                  <div className={styles.convText}>
                    <span className={styles.convTitle}>{c.title}</span>
                    <span className={styles.convMeta}>
                      {relativeTime(c.updated_at, now)}
                      {c.document_count > 0 && ` · 📎 ${c.document_count}`}
                    </span>
                  </div>
                  <div className={styles.convActions}>
                    <button
                      title="Rename"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingId(c.id);
                        setEditTitle(c.title);
                      }}
                    >
                      ✎
                    </button>
                    <button
                      title="Delete"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteConversation(c.id);
                      }}
                    >
                      🗑
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ─── Chat column ───────────────────────────────────── */}
      <div
        className={styles.chatArea}
        onDragEnter={(e) => {
          if (!e.dataTransfer.types.includes("Files")) return;
          dragDepth.current++;
          setDragOver(true);
        }}
        onDragOver={(e) => e.dataTransfer.types.includes("Files") && e.preventDefault()}
        onDragLeave={() => {
          dragDepth.current = Math.max(0, dragDepth.current - 1);
          if (!dragDepth.current) setDragOver(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          dragDepth.current = 0;
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
      >
        {dragOver && (
          <div className={styles.dropOverlay}>
            <div>📎 Drop files to attach them to this conversation</div>
          </div>
        )}

        {/* Header + document context */}
        <div className={styles.chatHeader}>
          <div className={styles.chatTitle}>{activeConv?.title ?? "New conversation"}</div>
          <div className={styles.contextBar}>
            {convDocs.map((d) => (
              <div key={d.id} className={`${styles.docChip} ${d.status === "failed" ? styles.docChipFailed : ""}`}>
                <button
                  className={styles.docChipMain}
                  onClick={() => setPreview({ documentId: d.id, title: d.title })}
                  title={d.status === "failed" ? d.error ?? "Failed" : `Preview ${d.title}`}
                >
                  {d.status === "processing" ? <span className={styles.miniSpinner} /> : <span className={styles.docKind}>{fileKind(d)}</span>}
                  <span className={styles.docChipTitle}>{d.title}</span>
                </button>
                <button className={styles.docChipX} onClick={() => handleDetach(d)} title="Detach from this conversation">
                  ×
                </button>
              </div>
            ))}
            {uploading > 0 && (
              <div className={styles.docChip}>
                <span className={styles.docChipMain}>
                  <span className={styles.miniSpinner} /> Uploading {uploading}…
                </span>
              </div>
            )}
            <button className={styles.ctxBtn} onClick={() => fileInputRef.current?.click()}>
              📎 Attach
            </button>
            <div className={styles.pickerWrap}>
              <button className={styles.ctxBtn} onClick={openPicker}>
                📚 From library
              </button>
              {pickerOpen && (
                <div className={styles.picker}>
                  <div className={styles.pickerHeader}>
                    <span>Ground this chat in…</span>
                    <button onClick={() => setPickerOpen(false)}>✕</button>
                  </div>
                  <div className={styles.pickerList}>
                    {libraryDocs.length === 0 && <p className={styles.emptyNote}>Library is empty</p>}
                    {libraryDocs.map((d) => {
                      const linked = convDocs.some((c) => c.id === d.id);
                      return (
                        <label key={d.id} className={styles.pickerItem}>
                          <input type="checkbox" checked={linked} onChange={() => toggleLibraryDoc(d)} />
                          <span className={styles.docKind}>{fileKind(d)}</span>
                          <span className={styles.pickerTitle}>{d.title}</span>
                          {d.status !== "ready" && <span className={styles.pickerStatus}>{d.status}</span>}
                        </label>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
            <input
              ref={fileInputRef}
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
          <div className={styles.scopeHint}>{scopeHint}</div>
        </div>

        {/* Messages */}
        <div className={styles.messages}>
          {messages.length === 0 && !sending && (
            <div className={styles.emptyState}>
              <div className={styles.emptyIcon}>✨</div>
              <h2>Ask your documents anything</h2>
              <p>
                Attach files to this conversation (or drop them here) to ground answers in them, or just ask —
                your whole library is searched by default. Every answer cites its sources; click a citation to
                see the exact passage.
              </p>
            </div>
          )}
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`${styles.bubble} ${msg.role === "user" ? styles.bubbleUser : styles.bubbleAI} animate-fade-in`}
            >
              <div className={styles.bubbleRole}>{msg.role === "user" ? "You" : "Assistant"}</div>
              {msg.role === "assistant" ? (
                <MessageContent
                  content={msg.content}
                  sources={msg.sources ?? []}
                  activeKey={preview?.messageId === msg.id ? preview.chunkId : null}
                  onCite={(src) => openCitation(msg.id, src)}
                />
              ) : (
                <div className={styles.bubbleContent}>{msg.content}</div>
              )}
            </div>
          ))}
          {sending && (
            <div className={`${styles.bubble} ${styles.bubbleAI} animate-fade-in`}>
              <div className={styles.bubbleRole}>Assistant</div>
              <div className={styles.typingDots}>
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {error && (
          <div className={styles.errorBar}>
            <span>{error}</span>
            <button onClick={() => setError(null)}>✕</button>
          </div>
        )}

        {/* Input */}
        <div className={styles.inputRow}>
          <textarea
            id="chat-input"
            className={`input ${styles.chatInput}`}
            placeholder={convDocs.length ? "Ask about the attached documents…" : "Ask a question about your documents…"}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            rows={2}
          />
          <button
            id="btn-send-message"
            className="btn btn-primary"
            onClick={handleSend}
            disabled={sending || !input.trim()}
            style={{ alignSelf: "flex-end", height: "44px" }}
          >
            {sending ? <span className="spinner" /> : "Send ↑"}
          </button>
        </div>
      </div>

      {/* ─── Citation / document preview ───────────────────── */}
      {preview && <DocumentPreview target={preview} onClose={closePreview} />}
    </div>
  );
}
