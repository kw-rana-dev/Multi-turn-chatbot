# RAG Studio (Document Ingestion & Chat Context)

An enterprise-ready, document-grounded AI chat and semantic search application. Upload documents into a global library or attach them directly to conversations, and chat with AI grounded in exact source text. Responses include clickable `[n]` citations that open an interactive side preview highlighting the exact cited passage and page number.

---

## ✨ Features

- **Document Ingestion & Parsing**:
  - Supports `.pdf`, `.txt`, `.md`, `.markdown`, `.csv`, `.json`, and `.log` files.
  - Automatic page boundary detection for PDFs.
  - Offset-preserving chunking (guarantees exact character-level citation mapping: `content == Document.content[char_start:char_end]`).
  - SHA-256 deduplication to prevent re-processing duplicate files.
  - Asynchronous background ingestion pipeline.
- **Precision RAG & Inline Citations**:
  - Inline `[n]` citations in markdown answers that link directly to the source passage.
  - Interactive side preview panel with text passage highlighting and PDF page jumping.
- **Flexible Retrieval Scope**:
  - **Conversation-scoped mode**: Retrieve strictly from attached conversation documents with no arbitrary similarity cutoff.
  - **Library-wide mode**: Fall back to searching the global document library when no documents are attached.
- **Smart Conversation Memory**:
  - Context window tracking with sliding-window recent turn retention.
  - **Rolling Cumulative Summarization**: Synthesizes and preserves key topics every 10 messages so long conversations never lose context.
  - Short follow-up query rewriting (combines previous turns for optimal embedding quality).
- **Offline / Stub Development Mode**:
  - Works fully offline out of the box when `OPENROUTER_API_KEY` is omitted using deterministic pseudo-random embeddings and stub answers.
- **Modern UI**:
  - Next.js 16 (App Router), React 19, CSS Modules with strict design tokens, responsive layout, dark theme.

---

## 🏗️ Architecture & Tech Stack

| Layer | Technology | Role |
|---|---|---|
| **Frontend** | Next.js 16, React 19, `react-markdown`, CSS Modules | Interactive chat, document management, semantic search, and side-by-side snippet preview |
| **Backend API** | FastAPI (Python 3.12, async), SQLAlchemy 2 + asyncpg, Pydantic v2 | Ingestion workflows, chunking, retrieval orchestration, prompt generation |
| **Vector Database** | PostgreSQL 16 + `pgvector` | Metadata storage, conversation history, and cosine similarity vector search |
| **Object Storage** | MinIO (S3-compatible) | Persisting raw uploaded documents and files |
| **LLM & Embeddings** | OpenRouter (`meta-llama/llama-3.3-70b-instruct`, `text-embedding-3-small`) | Embeddings and grounded conversational generation (with fallback stubs) |

---

## 🚀 Quick Start

### 1. Prerequisites
- [Docker](https://docs.docker.com/get-docker/) & [Docker Compose](https://docs.docker.com/compose/)

### 2. Setup Environment
Clone the repository and copy the example environment file:
```bash
cp .env.example .env
```

*(Optional)* Add your [OpenRouter API Key](https://openrouter.ai/) in `.env` to enable live LLM generation and real vector embeddings:
```dotenv
OPENROUTER_API_KEY=sk-or-v1-...
```
> **Note**: If `OPENROUTER_API_KEY` is left blank, the application will run in **offline stub mode** (mock embeddings and responses) without incurring any API credits.

### 3. Launch Services
Run all services with Docker Compose:
```bash
docker compose up -d --build
```

### 4. Access the Services

| Service | URL | Notes |
|---|---|---|
| **Frontend Application** | [http://localhost:3010](http://localhost:3010) | Main user interface |
| **API & Swagger Docs** | [http://localhost:8010/docs](http://localhost:8010/docs) | Interactive FastAPI documentation |
| **MinIO Console** | [http://localhost:9011](http://localhost:9011) | Credentials: `minioadmin` / `minioadmin` |
| **PostgreSQL Database** | `localhost:5433` | Database: `ragdb`, User: `raguser` |

---

## 📂 Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application & lifecycle handlers
│   │   ├── config.py            # Pydantic settings & environment configuration
│   │   ├── database.py          # Async database engine & session dependency
│   │   ├── models.py            # SQLAlchemy models (Document, Chunk, Conversation, Message)
│   │   ├── schemas.py           # Pydantic request/response schemas
│   │   ├── migrations.py        # Automatic table creation & schema upgrades
│   │   ├── routers/
│   │   │   ├── chat.py          # Conversation, messaging, RAG chat, attachments
│   │   │   ├── documents.py     # Document library CRUD, upload, reindex, preview
│   │   │   └── search.py        # Semantic vector search endpoint
│   │   └── services/
│   │       ├── ingestion.py     # Document upload & asynchronous background processing
│   │       ├── extraction.py    # Raw bytes -> text + PDF page span extractor
│   │       ├── chunking.py      # Character-offset preserving chunk splitter
│   │       ├── rag.py           # Retrieval, prompts, rolling summary & citation mapping
│   │       ├── embeddings.py    # OpenRouter API client (with retry & stub mode)
│   │       └── storage.py       # MinIO S3 client wrapper
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js App Router root layout & main shell
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx    # Chat interface, attachments, and messaging
│   │   │   ├── DocumentPreview.tsx # Side panel highlighting cited text / PDF page
│   │   │   ├── DocumentsPanel.tsx  # Document library management & upload
│   │   │   ├── MessageContent.tsx  # Markdown renderer with [n] citation buttons
│   │   │   └── SearchPanel.tsx     # Semantic search tab
│   │   └── lib/
│   │       └── api.ts           # Type-safe API client
│   └── Dockerfile
├── db/
│   └── init.sql                 # Vector extension initialization
├── docker-compose.yml           # Multi-container orchestration
└── AGENTS.md                    # Coding conventions & architecture notes for AI agents
```

---

## 📖 Key Workflows

### 1. Ingestion Pipeline
1. Files uploaded via the Library (`POST /api/v1/documents/upload-file`) or as Chat Attachments (`POST /api/v1/chat/conversations/{id}/attachments`) are stored in MinIO under `documents/{doc_id}/{filename}`.
2. An asynchronous background task extracts text, calculates page spans (for PDFs), and chunks the content using strict character offset tracking.
3. Chunks are embedded and stored in PostgreSQL using pgvector.
4. Duplicate files (matched by SHA-256) are automatically deduplicated.

### 2. RAG & Grounded Citations
1. When a user asks a question, the backend inspects the conversation:
   - If documents are attached, retrieval is scoped strictly to those documents.
   - If no documents are attached, search queries the global library.
2. Short follow-up questions are combined with prior turn context to ensure high-quality vector embeddings.
3. The LLM generates an answer citing passages using `[n]`.
4. The API formats citations with exact `char_start` and `char_end` indexes in the original document text. Clicking citations in the UI immediately opens the preview pane scrolled and highlighted to the exact text.

### 3. Rolling Conversation Summarization
- To prevent prompt blowups while preserving long-term conversational memory, every 10 messages (`SUMMARY_TRIGGER_INTERVAL = 10`), the backend extracts unsummarized turns and asks the LLM to synthesize an updated, cumulative chronological summary.
- This summary is fed into future LLM generation calls alongside recent turns and retrieved chunks.

---

## 🛠️ Development & Helpful Commands

### View Logs
```bash
# View backend logs
docker compose logs -f backend

# View frontend logs
docker compose logs -f frontend
```

### Hot Reloading
Both `backend/` and `frontend/` source directories are bind-mounted into their respective containers:
- Python code edits reload automatically with `uvicorn --reload`.
- Frontend React / Next.js code hot-reloads with Next.js development server.

### Rebuilding Containers
If you modify `backend/requirements.txt` or `frontend/package.json`:
```bash
docker compose up -d --build -V frontend
docker compose up -d --build backend
```

---

## 📄 License
This project is open-source. See the repository for license details.
