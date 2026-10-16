from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "RAG Backend"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://raguser:ragpassword@localhost:5432/ragdb"

    # Security
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3010",
        "http://localhost:3001",
    ]

    # ─── OpenRouter ───────────────────────────────────────────────────────────────
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_CHAT_MODEL: str = "meta-llama/llama-3.3-70b-instruct"
    OPENROUTER_EMBEDDING_MODEL: str = "openai/text-embedding-3-small"

    # ─── MinIO (original file storage) ────────────────────────────────────────────
    MINIO_ENDPOINT: str = "localhost:9010"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "documents"
    MINIO_SECURE: bool = False
    MAX_UPLOAD_MB: int = 50

    # ─── Chunking ─────────────────────────────────────────────────────────────────
    CHUNK_SIZE: int = 1000          # characters per chunk
    CHUNK_OVERLAP: int = 200        # overlapping characters between chunks
    EMBED_BATCH_SIZE: int = 20      # max chunks per embedding API call

    # ─── Vector search ────────────────────────────────────────────────────────────
    EMBEDDING_DIMENSION: int = 1536  # 1536 = text-embedding-3-small
    TOP_K_CHUNKS: int = 5
    MIN_SIMILARITY_SCORE: float = 0.30  # discard chunks below this score (library-wide search only)
    SCOPED_TOP_K: int = 8               # chunks retrieved when a chat has attached documents (no score cutoff)

    # ─── Chat ─────────────────────────────────────────────────────────────────────
    CHAT_HISTORY_WINDOW: int = 6    # number of recent messages to include as context
    SUMMARY_TRIGGER_INTERVAL: int = 10  # generate/append summary after every N messages


@lru_cache
def get_settings() -> Settings:
    return Settings()
