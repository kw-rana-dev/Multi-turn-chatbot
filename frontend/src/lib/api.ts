export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type DocumentStatus = "processing" | "ready" | "failed";

export interface Document {
  id: string;
  title: string;
  preview: string;
  source: string | null;
  filename: string | null;
  content_type: string | null;
  size_bytes: number | null;
  page_count: number | null;
  status: DocumentStatus;
  error: string | null;
  origin: "library" | "chat";
  has_file: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  chunk_count: number;
  duplicate: boolean;
}

export interface DocumentContent {
  id: string;
  title: string;
  content: string;
  content_type: string | null;
  has_file: boolean;
  pages: Array<{ page: number; start: number; end: number }> | null;
}

export interface Chunk {
  id: string;
  document_id: string;
  document_title: string | null;
  chunk_index: number;
  content: string;
  page: number | null;
  char_start: number | null;
  char_end: number | null;
  score: number | null;
}

/** Citation stored on an assistant message. `n` matches the [n] markers in its content. */
export interface Citation {
  n?: number; // absent on messages created before citations were numbered
  id: string;
  document_id: string;
  document_title?: string | null;
  chunk_index: number;
  page?: number | null;
  char_start?: number | null;
  char_end?: number | null;
  content: string;
  score: number | null;
  cited?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  document_count: number;
  message_count: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  sources: Citation[];
  created_at: string;
}

export interface ChatResponse {
  conversation_id: string;
  conversation_title: string;
  user_message: Message;
  assistant_message: Message;
  sources: Chunk[];
}

/** What the side preview should show: a document, optionally scrolled to a cited passage. */
export interface PreviewTarget {
  documentId: string;
  title?: string | null;
  page?: number | null;
  charStart?: number | null;
  charEnd?: number | null;
  snippet?: string | null;
  label?: string; // e.g. "[2]"
}

export function citationToTarget(c: Citation | Chunk, label?: string): PreviewTarget {
  return {
    documentId: c.document_id,
    title: c.document_title,
    page: c.page,
    charStart: c.char_start,
    charEnd: c.char_end,
    snippet: c.content,
    label,
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api/v1${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// ─── Documents ───────────────────────────────────────────────────────────────

export function uploadDocument(data: { title: string; content: string; source?: string }) {
  return request<Document>("/documents/", { method: "POST", ...json(data) });
}

export function uploadFile(file: File, title?: string) {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  return request<Document>("/documents/upload-file", { method: "POST", body: form });
}

export function listDocuments(origin: "library" | "chat" | "all" = "library") {
  return request<Document[]>(`/documents/?origin=${origin}&limit=200`);
}

export function getDocumentContent(id: string) {
  return request<DocumentContent>(`/documents/${id}/content`);
}

export function documentFileUrl(id: string, download = false) {
  return `${API_BASE}/api/v1/documents/${id}/file${download ? "?download=true" : ""}`;
}

export function reindexDocument(id: string) {
  return request<Document>(`/documents/${id}/reindex`, { method: "POST" });
}

export function deleteDocument(id: string) {
  return request<void>(`/documents/${id}`, { method: "DELETE" });
}

// ─── Conversations ───────────────────────────────────────────────────────────

export function listConversations() {
  return request<Conversation[]>("/chat/conversations");
}

export function createConversation(title = "New Conversation", documentIds: string[] = []) {
  return request<Conversation>("/chat/conversations", {
    method: "POST",
    ...json({ title, document_ids: documentIds }),
  });
}

export function renameConversation(id: string, title: string) {
  return request<Conversation>(`/chat/conversations/${id}`, { method: "PATCH", ...json({ title }) });
}

export function deleteConversation(id: string) {
  return request<void>(`/chat/conversations/${id}`, { method: "DELETE" });
}

export function getMessages(conversationId: string) {
  return request<Message[]>(`/chat/conversations/${conversationId}/messages`);
}

export function sendMessage(conversationId: string, content: string) {
  return request<ChatResponse>(`/chat/conversations/${conversationId}/messages`, {
    method: "POST",
    ...json({ content }),
  });
}

export function getConversationDocuments(conversationId: string) {
  return request<Document[]>(`/chat/conversations/${conversationId}/documents`);
}

export function linkConversationDocuments(conversationId: string, documentIds: string[]) {
  return request<Document[]>(`/chat/conversations/${conversationId}/documents`, {
    method: "POST",
    ...json({ document_ids: documentIds }),
  });
}

export function attachFile(conversationId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<Document>(`/chat/conversations/${conversationId}/attachments`, { method: "POST", body: form });
}

export function unlinkConversationDocument(conversationId: string, documentId: string) {
  return request<void>(`/chat/conversations/${conversationId}/documents/${documentId}`, { method: "DELETE" });
}

// ─── Search ───────────────────────────────────────────────────────────────────

export function semanticSearch(query: string, top_k = 5) {
  return request<{ query: string; chunks: Chunk[] }>("/search/", { method: "POST", ...json({ query, top_k }) });
}

// ─── Formatting ──────────────────────────────────────────────────────────────

export const ACCEPTED_FILE_TYPES = ".pdf,.txt,.md,.markdown,.csv,.json,.log";

export function formatBytes(bytes: number | null | undefined) {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let n = bytes;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export function fileKind(doc: Pick<Document, "filename" | "content_type">) {
  const ext = doc.filename?.split(".").pop()?.toLowerCase();
  return ext && ext.length <= 8 ? ext.toUpperCase() : "TXT";
}
