from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import SearchRequest, SearchResponse
from app.services.rag import similarity_search

router = APIRouter(prefix="/search", tags=["Search"])


@router.post("/", response_model=SearchResponse)
async def semantic_search(
    payload: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Semantic similarity search over the library, or over specific documents if document_ids is given."""
    chunks = await similarity_search(
        db,
        payload.query,
        top_k=payload.top_k,
        min_score=-1.0 if payload.document_ids else None,
        document_ids=payload.document_ids,
    )
    return SearchResponse(query=payload.query, chunks=chunks)
