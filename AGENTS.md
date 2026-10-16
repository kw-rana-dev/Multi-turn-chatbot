# AGENTS.md — RAG Studio (chat-context)

Guidance for AI coding agents and new contributors. Read this before changing code.

## What this is

A document-grounded chat app. Users upload documents (to a shared **library** or directly into a **conversation**), ask questions across many parallel conversations, and get answers with inline `[n]` citations that open a side preview highlighting the exact cited passage.

| Layer | Tech | Location |
|---|---|---|
| Frontend | Next.js 16 (App Router, client components, CSS Modules), React 19, `react-markdown` + `remark-gfm` | `frontend/` |
| API | FastAPI (async), SQLAlchemy 2 async + asyncpg, Pydantic v2 | `backend/app/` |
| Vectors + metadata | PostgreSQL 16 + pgvector | `db` service |
| Original files | MinIO (S3-compatible) | `minio` service |
| LLM + embeddings | OpenRouter (OpenAI-compatible API) | `backend/app/services/embeddings.py` |

## Running it

```bash
cp .env.example .env            # set OPENROUTER_API_KEY (empty = deterministic stubs, no network)
docker compose up -d --build
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3010 |
| API + Swagger | http://localhost:8010/docs |
| MinIO console | http://localhost:9011 (minioadmin / minioadmin) |
| Postgres | localhost:5433 (raguser / ragpassword / ragdb) |

The backend and frontend bind-mount their source, so code edits hot-reload. **Rebuild the image after changing `requirements.txt` or `package.json`.** The frontend also keeps `node_modules` in an anonymous volume, so add `-V` (`docker compose up -d --build -V frontend`) to pick up new packages.

With no `OPENROUTER_API_KEY`, embeddings are deterministic pseudo-random vectors and the chat returns a stub answer containing `[1]`. That's enough to exercise the whole pipeline end to end offline, but retrieval quality is meaningless.

## Repository map

```
backend/app/
  main.py              FastAPI app; lifespan runs migrations, ensures MinIO bucket, re-queues stuck ingestion jobs
  config.py            All settings (pydantic-settings, read from env / .env)
  database.py          Async engine, session factory, get_db dependency
  migrations.py        create_all + idempotent ALTERs (see "Schema changes")
  models.py            Document, DocumentChunk, Conversation, ConversationDocument, Message
  schemas.py           Pydantic request/response models
  routers/
    documents.py       Library CRUD, upload, content/file/chunks, reindex. Also shared helpers (document_responses, read_upload)
    chat.py            Conversations, per-conversation documents/attachments, messages (RAG), /ask
    search.py          Semantic search
  services/
    storage.py         MinIO wrapper (sync SDK → asyncio.to_thread)
    extraction.py      bytes → text (+ PDF page spans); supported extensions live here
    chunking.py        Offset-preserving splitter (chunks are exact slices of Document.content)
    ingestion.py       Upload → MinIO → background job: extract → chunk → embed → status
    embeddings.py      OpenRouter embeddings/chat, retries, stub fallback
    rag.py             Similarity search, conversation-scoped retrieval, prompt, citations, summaries
db/init.sql            Enables pgvector only; the app owns the tables
frontend/src/
  app/page.tsx         Shell with Chat / Documents / Search tabs
  lib/api.ts           Typed API client + shared types (Document, Citation, PreviewTarget…)
  components/
    ChatPanel.tsx      Conversation list, context bar (attach / pick from library), messages, preview
    MessageContent.tsx Markdown rendering; turns [n] into citation buttons + a source-chip row
    DocumentPreview.tsx Side panel: full text with highlighted passage + page markers, or the original file
    DocumentsPanel.tsx Library management (status, reindex, download, delete, filters)
    SearchPanel.tsx    Semantic search with click-to-preview
```

## Core flows

### Ingestion (asynchronous)
1. `POST /documents/upload-file` (library) or `POST /chat/conversations/{id}/attachments` (chat) runs `read_upload`, which validates the extension and the `MAX_UPLOAD_MB` limit.
2. Dedupe by SHA-256: an identical library upload returns the existing doc with `duplicate: true` (HTTP 200). An identical chat attachment reuses any existing doc and just links it.
3. `create_document` stores the bytes in MinIO at `documents/{doc_id}/{safe_filename}` and inserts a `Document` with `status=processing`.
4. The router **commits first, then** calls `schedule_processing(doc.id)`. The job opens its own session and would not see an uncommitted row.
5. `process_document` extracts the text, splits it into chunks, embeds `"{title}\n\n{chunk}"`, replaces the doc's chunks, and sets `status=ready`. On error it sets `failed` and fills `error`.
6. The frontend polls every 2 s while any visible doc is `processing`.

Jobs are in-process `asyncio` tasks. Docs left in `processing` by a restart are re-queued on startup. Moving to a real queue (arq, Celery, …) means replacing `schedule_processing` only.

### Chat / retrieval
- A conversation's documents come from the `conversation_documents` link table. **If it has any, retrieval is restricted to them** (`SCOPED_TOP_K`, no score cutoff). **If not, the whole library is searched** (`origin='library'`, `TOP_K_CHUNKS`, `MIN_SIMILARITY_SCORE`).
- Chat attachments (`origin='chat'`) are private: they never appear in library-wide search or the default document list.
- Short follow-up questions are embedded together with the previous user turn (`_retrieval_query`).
- Old `[n]` markers are stripped from assistant history before it goes back to the LLM, because they refer to old source lists.
- The first message auto-titles the conversation. A rolling summary is appended every `SUMMARY_TRIGGER_INTERVAL` messages.

### Citations contract (backend ↔ frontend)
`Message.sources` is a JSON list built by `rag.build_citations`:

```json
{ "n": 1, "id": "<chunk id>", "document_id": "…", "document_title": "…", "chunk_index": 0,
  "page": 3, "char_start": 1200, "char_end": 2150, "content": "<chunk text>", "score": 0.82, "cited": true }
```

- `n` is the number the LLM was shown and must match the `[n]` markers in `Message.content`.
- `char_start`/`char_end` index into `Document.content` (served by `GET /documents/{id}/content`), and `content == Document.content[char_start:char_end]` must always hold. `chunking.py` guarantees it. Don't add post-processing (strip, join, replace) that breaks it.
- `page` is 1-based and only set for PDFs. Chunks never cross a page boundary.
- Messages created before this contract existed lack `n`, offsets and titles. The frontend falls back to positional numbering and snippet search (`numberedSources`, `resolveRange`), so keep those fallbacks.

If you change the prompt format, keep the instruction to cite as `[n]`. `MessageContent.linkCitations` only recognizes `[1]` / `[1, 3]`.

## API surface (prefix `/api/v1`)

| Method | Path | Notes |
|---|---|---|
| POST | `/documents/` | Pasted text (stored as `.txt` in MinIO) |
| POST | `/documents/upload-file` | multipart `file` (+ optional `title`, `source`, `chunk_size`, `chunk_overlap`) |
| GET | `/documents/?origin=library\|chat\|all&q=` | List with chunk counts |
| GET | `/documents/{id}` · `/content` · `/file[?download=true]` · `/chunks` | Metadata, full text + page spans, original bytes, chunks |
| POST | `/documents/{id}/reindex` | Re-run ingestion from the stored original |
| DELETE | `/documents/{id}` | Row + chunks + links (DB cascade) + MinIO object |
| GET/POST | `/chat/conversations` | List / create (`document_ids` optional) |
| GET/PATCH/DELETE | `/chat/conversations/{id}` | Get / rename / delete (documents are kept) |
| GET/POST | `/chat/conversations/{id}/documents` | List / link existing docs |
| DELETE | `/chat/conversations/{id}/documents/{doc_id}` | Unlink only |
| POST | `/chat/conversations/{id}/attachments` | Upload into the conversation |
| GET/POST | `/chat/conversations/{id}/messages` | History / send (full RAG turn) |
| POST | `/chat/ask` | One-shot library question |
| POST | `/search/` | `{query, top_k, document_ids?}` |

## Conventions

**Backend**
- Everything is async. Never call blocking I/O on the event loop: wrap sync SDKs (MinIO, pypdf) in `asyncio.to_thread`.
- Routers stay thin. Business logic goes in `services/`. Shared response builders currently live in `routers/documents.py` and are imported by `chat.py`.
- Reading server-generated columns (`updated_at`) after `commit()` triggers a lazy load and raises `MissingGreenlet`. Call `await db.refresh(obj)` before serializing (see `reindex_document`).
- Use `document_responses(db, docs)` to serialize lists. It batches chunk counts instead of issuing N+1 queries.
- Settings come only from `config.py` and `get_settings()`. Add new knobs there and to `.env.example`.

**Frontend**
- All components are client components (`"use client"`) using CSS Modules and the design tokens in `app/globals.css` (`--bg-*`, `--accent-*`, `--text-*`). Reuse the tokens; don't hard-code new palettes.
- All HTTP calls go through `lib/api.ts`. `request()` surfaces FastAPI `detail` messages as `Error.message`.
- The lint config enforces React Compiler purity rules: no `setState` synchronously inside effect bodies, no `Date.now()` and other impure calls during render. Derive state, or set it inside promise callbacks.
- `DocumentPreview` caches document text per id. Call `invalidatePreviewCache(id)` after reindexing or deleting.
- **Next.js 16 has breaking changes vs. older versions.** Read `frontend/AGENTS.md` and `frontend/node_modules/next/dist/docs/` before using framework APIs.
- Both `next.config.js` and `next.config.ts` exist. **Next loads `next.config.js`** (the build log says so), so `next.config.ts` is currently ignored. Consolidate them before relying on either.

## Schema changes

Postgres starts with only the `vector` extension (`db/init.sql`). On every boot, `migrations.run_migrations` runs `Base.metadata.create_all` (new tables) followed by `ADD COLUMN IF NOT EXISTS` statements (new columns on existing tables). To add a column:
1. Add it to `models.py`.
2. Append the matching idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS …` to `UPGRADES`. Use `server_default` for NOT NULL columns.
3. If it's indexed with `index=True`, add `CREATE INDEX IF NOT EXISTS ix_<table>_<column>`, using that exact name so fresh and upgraded databases match.

Changing `EMBEDDING_DIMENSION` requires recreating `document_chunks.embedding` and reindexing every document. `ALTER` won't convert the vectors.

## Testing

There is no automated test suite yet (pytest is in `requirements.txt`). Minimum checks before handing off:

```bash
# frontend
cd frontend && npx tsc --noEmit && npx eslint src && npm run build
# backend: stack up, then exercise the API (Swagger at /docs) — upload a PDF, wait for status=ready,
# check GET /documents/{id}/chunks satisfies content == document.content[char_start:char_end],
# attach a file to a conversation, send a message, verify sources[].n / cited / document_id scope.
```

Run with an empty `OPENROUTER_API_KEY` to test without spending API credits.

## Gotchas

- `.env` holds real secrets and is git-ignored. Never copy keys into `.env.example`, docs, or code.
- CORS is wide open (`allow_origins=["*"]`) and there is no auth. Every user sees every conversation and document. Add auth before any multi-user deployment.
- Original files are proxied through the API (`/documents/{id}/file`) rather than served from presigned MinIO URLs, because MinIO's in-network hostname (`minio:9000`) isn't reachable from the browser. Files are read fully into memory, bounded by `MAX_UPLOAD_MB`.
- Scanned or image-only PDFs have no text layer and end up `failed` ("No extractable text"). There is no OCR.
- The PDF "Original" preview uses the browser's built-in viewer with `#page=N`. It jumps to the page but can't highlight the passage; the Text view does.
