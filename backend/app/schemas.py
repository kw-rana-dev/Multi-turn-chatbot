import uuid
from datetime import datetime
from pydantic import BaseModel, Field


# ─── Document Schemas ──────────────────────────────────────────────────────────

class DocumentCreate(BaseModel):
    title: str
    content: str
    source: str | None = None
    metadata: dict = Field(default_factory=dict)


class DocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    preview: str                 # first ~400 chars of extracted text
    source: str | None
    filename: str | None
    content_type: str | None
    size_bytes: int | None
    page_count: int | None
    status: str                  # processing | ready | failed
    error: str | None
    origin: str                  # library | chat
    has_file: bool               # original stored in MinIO
    metadata: dict
    created_at: datetime
    updated_at: datetime
    chunk_count: int = 0
    duplicate: bool = False      # upload matched an existing document


class PageSpan(BaseModel):
    page: int
    start: int
    end: int


class DocumentContentResponse(BaseModel):
    id: uuid.UUID
    title: str
    content: str
    content_type: str | None
    has_file: bool
    pages: list[PageSpan] | None


# ─── Chunk Schemas ─────────────────────────────────────────────────────────────

class ChunkResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str | None = None
    chunk_index: int
    content: str
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    score: float | None = None

    model_config = {"from_attributes": True}


# ─── Search Schemas ────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[uuid.UUID] | None = None


class SearchResponse(BaseModel):
    query: str
    chunks: list[ChunkResponse]


# ─── Conversation Schemas ──────────────────────────────────────────────────────

class ConversationCreate(BaseModel):
    title: str = "New Conversation"
    document_ids: list[uuid.UUID] = Field(default_factory=list)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    summary: str | None = None
    last_summarized_count: int = 0
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    message_count: int = 0

    model_config = {"from_attributes": True}


class LinkDocumentsRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1)


# ─── Message Schemas ───────────────────────────────────────────────────────────

class MessageCreate(BaseModel):
    content: str = Field(min_length=1)


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    sources: list
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    conversation_title: str
    user_message: MessageResponse
    assistant_message: MessageResponse
    sources: list[ChunkResponse]
