"""
Schema bootstrap.

`Base.metadata.create_all` creates missing tables but never alters existing
ones, so columns added after a table was first created are patched in here
with idempotent `ADD COLUMN IF NOT EXISTS`. Safe to run on every startup.
Move to Alembic once the schema stabilises.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from app.database import Base

UPGRADES = [
    # documents
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS filename TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_type TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS size_bytes BIGINT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS checksum VARCHAR(64)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_key TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_count INTEGER",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'ready'",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS error TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS origin VARCHAR(20) NOT NULL DEFAULT 'library'",
    "CREATE INDEX IF NOT EXISTS ix_documents_checksum ON documents (checksum)",
    # document_chunks
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS page INTEGER",
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS char_start INTEGER",
    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS char_end INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id ON document_chunks (document_id)",
    # conversations
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary TEXT",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_summarized_count INTEGER NOT NULL DEFAULT 0",
]


async def run_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        for stmt in UPGRADES:
            await conn.execute(text(stmt))
