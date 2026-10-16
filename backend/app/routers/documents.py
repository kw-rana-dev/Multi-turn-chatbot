import uuid
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.database import get_db
from app.models import Document, DocumentChunk
from app.schemas import DocumentCreate, DocumentResponse, DocumentContentResponse, PageSpan, ChunkResponse
from app.services import storage
from app.services.extraction import SUPPORTED_EXTENSIONS, file_extension
from app.services.ingestion import checksum_of, create_document, find_duplicate, schedule_processing
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/documents", tags=["Documents"])


# ─── Helpers (also used by the chat router) ───────────────────────────────────

def document_response(doc: Document, chunk_count: int, duplicate: bool = False) -> DocumentResponse:
    preview = doc.content[:400] + ("…" if len(doc.content) > 400 else "")
    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        preview=preview,
        source=doc.source,
        filename=doc.filename,
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        page_count=doc.page_count,
        status=doc.status,
        error=doc.error,
        origin=doc.origin,
        has_file=bool(doc.storage_key),
        metadata={k: v for k, v in (doc.metadata_ or {}).items() if k != "pages"},
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        chunk_count=chunk_count,
        duplicate=duplicate,
    )


async def document_responses(db: AsyncSession, docs: list[Document]) -> list[DocumentResponse]:
    if not docs:
        return []
    counts = dict((await db.execute(
        select(DocumentChunk.document_id, func.count())
        .where(DocumentChunk.document_id.in_([d.id for d in docs]))
        .group_by(DocumentChunk.document_id)
    )).all())
    return [document_response(d, counts.get(d.id, 0)) for d in docs]


async def read_upload(file: UploadFile) -> tuple[bytes, str]:
    """Validate type and size; returns (raw bytes, filename)."""
    filename = file.filename or "upload.txt"
    if file_extension(filename) not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="File is empty.")
    if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_MB} MB limit.")
    return raw, filename


async def get_document_or_404(db: AsyncSession, document_id: uuid.UUID) -> Document:
    doc = await db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def title_from_filename(filename: str) -> str:
    return filename.rsplit(".", 1)[0] or filename


# ─── Upload text document ─────────────────────────────────────────────────────

@router.post("/", response_model=DocumentResponse, status_code=201)
async def upload_document(
    payload: DocumentCreate,
    chunk_size: int = Query(default=None, ge=200, le=4000, description="Characters per chunk"),
    chunk_overlap: int = Query(default=None, ge=0, le=500, description="Overlap between chunks"),
    db: AsyncSession = Depends(get_db),
):
    """Ingest pasted text. Stored in MinIO as a .txt file and indexed in the background."""
    if not payload.content.strip():
        raise HTTPException(status_code=422, detail="Content is empty.")
    doc = await create_document(
        db,
        raw=payload.content.encode("utf-8"),
        filename=f"{payload.title}.txt",
        title=payload.title,
        source=payload.source,
        metadata=payload.metadata,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    await db.commit()
    schedule_processing(doc.id)
    return document_response(doc, 0)


# ─── Upload file ──────────────────────────────────────────────────────────────

@router.post("/upload-file", response_model=DocumentResponse, status_code=201)
async def upload_file(
    response: Response,
    file: UploadFile = File(...),
    title: str = Form(default=""),
    source: str = Form(default=""),
    chunk_size: int | None = Form(default=None, ge=200, le=4000),
    chunk_overlap: int | None = Form(default=None, ge=0, le=500),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a file to the library (pdf, txt, md, csv, json).
    The original goes to MinIO; extraction, chunking and embedding run in the
    background — poll GET /documents/{id} until status is `ready`.
    Re-uploading identical bytes returns the existing document (duplicate=true).
    """
    raw, filename = await read_upload(file)

    existing = await find_duplicate(db, checksum_of(raw), origin="library")
    if existing:
        response.status_code = 200
        return (await document_responses(db, [existing]))[0].model_copy(update={"duplicate": True})

    doc = await create_document(
        db,
        raw=raw,
        filename=filename,
        title=title.strip() or title_from_filename(filename),
        source=source or None,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    await db.commit()
    schedule_processing(doc.id)
    return document_response(doc, 0)


# ─── List documents ───────────────────────────────────────────────────────────

@router.get("/", response_model=list[DocumentResponse])
async def list_documents(
    origin: str = Query(default="library", pattern="^(library|chat|all)$"),
    q: str | None = Query(default=None, description="Filter by title"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List documents with chunk counts. origin: library (default) | chat (attachments) | all."""
    stmt = select(Document).order_by(Document.created_at.desc()).offset(skip).limit(limit)
    if origin != "all":
        stmt = stmt.where(Document.origin == origin)
    if q:
        stmt = stmt.where(Document.title.ilike(f"%{q}%"))
    docs = list((await db.execute(stmt)).scalars().all())
    return await document_responses(db, docs)


# ─── Get single document ──────────────────────────────────────────────────────

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    doc = await get_document_or_404(db, document_id)
    return (await document_responses(db, [doc]))[0]


@router.get("/{document_id}/content", response_model=DocumentContentResponse)
async def get_document_content(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Full extracted text plus page spans — used by the citation side preview."""
    doc = await get_document_or_404(db, document_id)
    pages = (doc.metadata_ or {}).get("pages")
    return DocumentContentResponse(
        id=doc.id,
        title=doc.title,
        content=doc.content,
        content_type=doc.content_type,
        has_file=bool(doc.storage_key),
        pages=[PageSpan(page=i + 1, start=s, end=e) for i, (s, e) in enumerate(pages)] if pages else None,
    )


@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    download: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """Stream the original file from MinIO (inline for preview, or as an attachment)."""
    doc = await get_document_or_404(db, document_id)
    if not doc.storage_key:
        raise HTTPException(status_code=404, detail="No original file stored for this document")
    data = await storage.get_object(doc.storage_key)
    disposition = "attachment" if download else "inline"
    filename = doc.filename or "document"
    return Response(
        content=data,
        media_type=doc.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/{document_id}/chunks", response_model=list[ChunkResponse])
async def list_document_chunks(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    doc = await get_document_or_404(db, document_id)
    result = await db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index)
    )
    return [
        ChunkResponse.model_validate(c).model_copy(update={"document_title": doc.title})
        for c in result.scalars().all()
    ]


# ─── Re-index ─────────────────────────────────────────────────────────────────

@router.post("/{document_id}/reindex", response_model=DocumentResponse, status_code=202)
async def reindex_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Re-extract, re-chunk and re-embed from the stored original (e.g. after changing chunking or embedding model)."""
    doc = await get_document_or_404(db, document_id)
    if doc.status == "processing":
        raise HTTPException(status_code=409, detail="Document is already being processed")
    doc.status = "processing"
    doc.error = None
    await db.commit()
    await db.refresh(doc)  # updated_at is server-generated; load it before serializing
    schedule_processing(doc.id)
    return (await document_responses(db, [doc]))[0]


# ─── Delete document ──────────────────────────────────────────────────────────

@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Delete the document, its chunks, its chat links and the original in MinIO."""
    doc = await get_document_or_404(db, document_id)
    storage_key = doc.storage_key
    await db.execute(delete(Document).where(Document.id == doc.id))
    await db.commit()
    if storage_key:
        await storage.delete_object(storage_key)
