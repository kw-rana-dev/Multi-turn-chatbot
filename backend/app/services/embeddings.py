"""
Embedding service — uses OpenRouter as the unified provider for both
vector embeddings and chat completions.

OpenRouter is OpenAI-API-compatible:
  Base URL : https://openrouter.ai/api/v1
  Embeddings: POST /embeddings  (model: openai/text-embedding-3-small)
  Chat      : POST /chat/completions  (any chat model on OpenRouter)
"""
import hashlib
import httpx
import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import get_settings

settings = get_settings()

DEFAULT_SYSTEM_PROMPT = "You are a helpful, concise assistant."


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:3010",
        "X-Title": "RAG Studio",
    }


# ─── Public API ───────────────────────────────────────────────────────────────

async def get_embedding(text: str) -> list[float]:
    """Get a single vector embedding via OpenRouter."""
    if settings.OPENROUTER_API_KEY:
        return await _openrouter_embedding(text)
    return _stub_embedding(text)


async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Get embeddings for a list of texts.
    Automatically splits into sub-batches of EMBED_BATCH_SIZE to avoid
    rate limits, and retries on transient errors.
    """
    if not settings.OPENROUTER_API_KEY:
        return [_stub_embedding(t) for t in texts]

    results: list[list[float]] = []
    batch_size = settings.EMBED_BATCH_SIZE

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        batch_embeddings = await _openrouter_embeddings_batch_with_retry(batch)
        results.extend(batch_embeddings)

    return results


async def generate_chat_response(
    prompt: str,
    history: list[dict] | None = None,
    system: str = DEFAULT_SYSTEM_PROMPT,
) -> str:
    """
    Generate a chat response via OpenRouter.

    Args:
        prompt: The current user prompt / RAG-augmented query.
        history: Optional list of prior messages in OpenAI format:
                 [{"role": "user"|"assistant", "content": "..."}]
        system: System prompt.
    """
    if settings.OPENROUTER_API_KEY:
        return await _openrouter_chat(prompt, history or [], system)
    return (
        "[Dev stub — set OPENROUTER_API_KEY in .env] "
        "RAG retrieved relevant context but no LLM is configured [1]."
    )


# ─── OpenRouter: single embedding ────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
)
async def _openrouter_embedding(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/embeddings",
            headers=_headers(),
            json={"model": settings.OPENROUTER_EMBEDDING_MODEL, "input": text},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


# ─── OpenRouter: batch embedding (with retry) ─────────────────────────────────

@retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    stop=stop_after_attempt(3),
)
async def _openrouter_embeddings_batch_with_retry(texts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/embeddings",
            headers=_headers(),
            json={"model": settings.OPENROUTER_EMBEDDING_MODEL, "input": texts},
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in data]


# ─── OpenRouter: chat completions ─────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    stop=stop_after_attempt(3),
)
async def _openrouter_chat(prompt: str, history: list[dict], system: str) -> str:
    # Build messages: system → history → current user prompt
    messages = [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": prompt},
    ]

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers=_headers(),
            json={
                "model": settings.OPENROUTER_CHAT_MODEL,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1536,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


# ─── Stub fallback ────────────────────────────────────────────────────────────

def _stub_embedding(text: str) -> list[float]:
    """Deterministic pseudo-embedding (stable across restarts) — NOT for production."""
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(settings.EMBEDDING_DIMENSION).astype(np.float32)
    vec /= np.linalg.norm(vec)
    return vec.tolist()
