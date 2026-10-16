# RAG Studio — Frontend

The web UI for RAG Studio: chat with your documents across multiple conversations, with inline citations that open the exact source passage in a side preview.

Built with **Next.js 16** (App Router), **React 19**, CSS Modules, and `react-markdown` + `remark-gfm`. It talks to the FastAPI backend in [`../backend`](../backend).

## Features

- **Multi-conversation chat.** A sidebar with search, rename and delete. Each conversation names itself from its first message.
- **Per-conversation documents.** Attach files to a chat (button or drag-and-drop), or pick documents from the library. If a chat has documents, answers come only from them; otherwise the whole library is searched.
- **Citations with side preview.** Answers cite sources as `[1]`, `[2]`… Click a citation or source chip to open a panel that scrolls to and highlights the cited passage, with page markers for PDFs. **Original** shows the actual file (PDFs open at the cited page). Press `Esc` to close.
- **Knowledge base management.** Upload PDF, TXT, MD, CSV or JSON files (several at once), or paste text. Each document shows its indexing status (indexing / ready / failed), size, pages and chunk count. You can preview, download the original, re-index or delete. Filter by Library / Chat attachments / All.
- **Semantic search.** Vector search over the library; click a result to see it in context.

## Running

### With Docker (recommended)

From the repository root:

```bash
docker compose up -d --build
```

Open **http://localhost:3010**. Source is bind-mounted, so edits hot-reload.

After changing `package.json`, rebuild and recreate the cached `node_modules` volume:

```bash
docker compose up -d --build -V frontend
```

### Locally (backend still in Docker)

```bash
cd frontend
npm install
echo NEXT_PUBLIC_API_URL=http://localhost:8010 > .env.local
npm run dev
```

Open **http://localhost:3000**.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend base URL. Use `http://localhost:8010` with the Docker setup. |

`NEXT_PUBLIC_*` values are inlined at build/dev-server start, so restart the dev server after changing it.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Production build |
| `npm run start` | Serve the production build |
| `npm run lint` | ESLint, including the React Compiler purity rules |
| `npx tsc --noEmit` | Type-check |

Run `npx tsc --noEmit && npm run lint && npm run build` before handing off changes.

## Project structure

```
src/
  app/
    page.tsx              App shell: sidebar + Chat / Documents / Search tabs, API status
    layout.tsx            Root layout and metadata
    globals.css           Design tokens (--bg-*, --accent-*, --text-*) and shared classes (.btn, .input, .badge)
  lib/
    api.ts                Typed API client and shared types (Document, Citation, PreviewTarget, …)
  components/
    ChatPanel.tsx         Conversations, per-chat documents, messages, attachments
    MessageContent.tsx    Markdown rendering; turns [n] markers into citation buttons + source chips
    DocumentPreview.tsx   Side panel: highlighted text view with page markers, or the original file
    DocumentsPanel.tsx    Knowledge base management
    SearchPanel.tsx       Semantic search with click-to-preview
```

## Notes for contributors

- **Next.js 16 has breaking changes** compared with older versions. Check [`AGENTS.md`](./AGENTS.md) and `node_modules/next/dist/docs/` before using framework APIs.
- Next loads **`next.config.js`**; `next.config.ts` is currently ignored. Consolidate them before changing config.
- All HTTP calls go through `src/lib/api.ts`. Errors surface the backend's `detail` message.
- Lint rejects `setState` called synchronously inside effects, and impure calls such as `Date.now()` during render. Derive state instead, or set it in promise callbacks.
- Citation numbers in the UI must match the `[n]` markers in the answer text. See the "Citations contract" in the root [`AGENTS.md`](../AGENTS.md) before changing either side.
