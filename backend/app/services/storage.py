"""
Object storage for original uploaded files (MinIO, S3-compatible).

Postgres holds the extracted text, chunks and embeddings; MinIO holds the
exact bytes the user uploaded so files can be previewed, downloaded and
re-indexed later. The MinIO SDK is synchronous, so every call runs in a
worker thread.
"""
import asyncio
import io
from functools import lru_cache
from minio import Minio
from minio.error import S3Error
from app.config import get_settings

settings = get_settings()
_bucket_ready = False


@lru_cache
def _client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def _ensure_bucket_sync() -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    client = _client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        try:
            client.make_bucket(settings.MINIO_BUCKET)
        except S3Error as e:
            if e.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise
    _bucket_ready = True


async def ensure_bucket() -> None:
    await asyncio.to_thread(_ensure_bucket_sync)


async def put_object(key: str, data: bytes, content_type: str) -> None:
    def _put() -> None:
        _ensure_bucket_sync()
        _client().put_object(
            settings.MINIO_BUCKET, key, io.BytesIO(data), length=len(data), content_type=content_type
        )

    await asyncio.to_thread(_put)


async def get_object(key: str) -> bytes:
    def _get() -> bytes:
        resp = _client().get_object(settings.MINIO_BUCKET, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    return await asyncio.to_thread(_get)


async def delete_object(key: str) -> None:
    await asyncio.to_thread(_client().remove_object, settings.MINIO_BUCKET, key)
