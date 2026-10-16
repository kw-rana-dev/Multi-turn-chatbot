"""
Document ingestion pipeline.

  upload ─► original bytes to MinIO ─► Document row (status=processing) ─► commit
         ─► background job: extract text ─► chunk (pages + char offsets)
                            ─► embed ─► replace chunks ─► status=ready | failed

Jobs run as asyncio tasks inside the API process. Documents left in
`processing` by a restart are re-queued on startup.
"""
import asyncio
import hashlib
import logging
import re
import uuid
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.models import Document, DocumentChunk
from app.services import storage
from app.services.chunking import chunk_document
from app.services.extraction import extract_text, guess_content_type
from app.services.embeddings import get_embeddings_batch
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Strong refs so running tasks aren't garbage-collected
_tasks: set[asyncio.Task] = set()


def checksum_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "file"


async def find_duplicate(db: AsyncSession, checksum: str, origin: str | None = None) -> Document | None:
    """An existing, non-failed document with identical bytes (optionally of a given origin)."""
    stmt = select(Document).where(Document.checksum == checksum, Document.status != "failed")
    if origin:
        stmt = stmt.where(Document.origin == origin)
    result = await db.execute(stmt.order_by(Document.created_at).limit(1))
    return result.scalar_one_or_none()


async def create_document(
    db: AsyncSession,
    *,
    raw: bytes,
    filename: str,
    title: str,
    origin: str = "library",
    source: str | None = None,
    metadata: dict | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> Document:
    """Store the original in MinIO and add a `processing` Document. Caller commits, then schedule_processing()."""
    doc_id = uuid.uuid4()
    content_type = guess_content_type(filename)
    storage_key = f"documents/{doc_id}/{_safe_filename(filename)}"
    await storage.put_object(storage_key, raw, content_type)

    doc = Document(
        id=doc_id,
        title=title,
        content="",
        source=source,
        filename=filename,
        content_type=content_type,
        size_bytes=len(raw),
        checksum=checksum_of(raw),
        storage_key=storage_key,
        status="processing",
        origin=origin,
        metadata_={
            **(metadata or {}),
            "chunk_size": chunk_size or settings.CHUNK_SIZE,
            "chunk_overlap": chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP,
        },
    )
    db.add(doc)
    await db.flush()
    return doc


def schedule_processing(document_id: uuid.UUID) -> None:
    task = asyncio.create_task(process_document(document_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def process_document(document_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, document_id)
        if not doc:
            return
        try:
            if doc.storage_key:
                raw = await storage.get_object(doc.storage_key)
                content, pages = await asyncio.to_thread(extract_text, raw, doc.filename or "file.txt")
            else:
                # Legacy rows ingested before MinIO: re-chunk the stored text
                content, pages = doc.content, None

            if not content.strip():
                raise ValueError("No extractable text found (scanned or image-only PDF?)")

            meta = doc.metadata_ or {}
            pieces = chunk_document(
                content,
                pages,
                chunk_size=meta.get("chunk_size") or settings.CHUNK_SIZE,
                chunk_overlap=meta.get("chunk_overlap", settings.CHUNK_OVERLAP),
            )
            # Prefixing the title gives each chunk's vector document-level context
            embeddings = await get_embeddings_batch([f"{doc.title}\n\n{p.content}" for p in pieces])

            await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
            for idx, (piece, embedding) in enumerate(zip(pieces, embeddings)):
                db.add(DocumentChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    content=piece.content,
                    page=piece.page,
                    char_start=piece.char_start,
                    char_end=piece.char_end,
                    embedding=embedding,
                    metadata_={
                        "char_count": len(piece.content),
                        "word_count": len(piece.content.split()),
                        "total_chunks": len(pieces),
                    },
                ))

            doc.content = content
            doc.page_count = len(pages) if pages else None
            doc.metadata_ = {**meta, "pages": [list(p) for p in pages] if pages else None}
            doc.status = "ready"
            doc.error = None
            await db.commit()
            logger.info("Indexed document %s (%d chunks)", doc.id, len(pieces))
        except Exception as e:
            logger.exception("Ingestion failed for document %s", document_id)
            await db.rollback()
            doc = await db.get(Document, document_id)
            if doc:
                doc.status = "failed"
                doc.error = str(e)[:500] or e.__class__.__name__
                await db.commit()


async def requeue_stuck_documents() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document.id).where(Document.status == "processing"))
        for doc_id in result.scalars().all():
            schedule_processing(doc_id)
