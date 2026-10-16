"""
RAG service:
  - similarity_search : cosine search, optionally scoped to specific documents
  - retrieve_for_conversation: scope = the chat's attached docs, else the library
  - generate_answer   : grounded prompt with numbered sources + history
  - build_citations   : persistable citation records for the UI side preview
"""
import re
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import Document, DocumentChunk, Conversation, ConversationDocument, Message
from app.services.embeddings import get_embedding, generate_chat_response
from app.schemas import ChunkResponse
from app.config import get_settings

settings = get_settings()

CITATION_RE = re.compile(r"\[(\d{1,3})\]")

ANSWER_SYSTEM_PROMPT = (
    "You are a careful research assistant answering questions about the user's documents.\n"
    "- Ground factual statements in the numbered sources provided in the user's message.\n"
    "- Cite inline with the source number in square brackets right after the claim, "
    "e.g. \"The term is 12 months [2].\" Use [1][3] for multiple sources. Never write [Source 1].\n"
    "- Only cite numbers that appear in the provided sources. Never invent citations.\n"
    "- If the sources don't contain the answer, say so plainly. You may then add general "
    "knowledge, clearly labelled as not coming from the documents.\n"
    "- Use Markdown (short paragraphs, lists, tables) when it helps readability."
)


# ─── Similarity Search ────────────────────────────────────────────────────────

async def similarity_search(
    db: AsyncSession,
    query: str,
    top_k: int | None = None,
    min_score: float | None = None,
    document_ids: list[uuid.UUID] | None = None,
) -> list[ChunkResponse]:
    """
    Cosine similarity search over ready documents using pgvector.

    document_ids=None searches the shared library (chat-only attachments are
    private to their conversation); a list restricts the search to those docs.
    """
    _top_k = top_k or settings.TOP_K_CHUNKS
    _min_score = min_score if min_score is not None else settings.MIN_SIMILARITY_SCORE

    query_embedding = await get_embedding(query)

    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    score = (1 - distance).label("score")

    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.content,
            DocumentChunk.page,
            DocumentChunk.char_start,
            DocumentChunk.char_end,
            Document.title.label("document_title"),
            score,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.embedding.is_not(None))
        .where(Document.status == "ready")
        .where(score >= _min_score)
        .order_by(distance)
        .limit(_top_k)
    )
    if document_ids is not None:
        stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))
    else:
        stmt = stmt.where(Document.origin == "library")

    result = await db.execute(stmt)

    return [
        ChunkResponse(
            id=row.id,
            document_id=row.document_id,
            document_title=row.document_title,
            chunk_index=row.chunk_index,
            content=row.content,
            page=row.page,
            char_start=row.char_start,
            char_end=row.char_end,
            score=round(float(row.score), 4),
        )
        for row in result.all()
    ]


def _retrieval_query(query: str, history: list[dict]) -> str:
    """Short follow-ups ("and the second one?") embed poorly alone; prefix the previous user turn."""
    if len(query.split()) >= 12:
        return query
    previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    return f"{previous}\n{query}" if previous else query


async def retrieve_for_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    query: str,
    history: list[dict],
) -> tuple[list[ChunkResponse], list[Document]]:
    """Returns (chunks, attached_documents). Attached docs → scoped search with no score cutoff."""
    attached = await list_conversation_documents(db, conversation_id)
    search_query = _retrieval_query(query, history)
    if attached:
        chunks = await similarity_search(
            db,
            search_query,
            top_k=settings.SCOPED_TOP_K,
            min_score=-1.0,  # user explicitly chose these docs — always return the best matches
            document_ids=[d.id for d in attached],
        )
    else:
        chunks = await similarity_search(db, search_query)
    return chunks, attached


# ─── LLM Generation (RAG) ────────────────────────────────────────────────────

async def generate_answer(
    query: str,
    context_chunks: list[ChunkResponse],
    conversation_history: list[dict] | None = None,
    conversation_summary: str | None = None,
    attached_documents: list[Document] | None = None,
) -> str:
    """Build a grounded prompt with numbered sources and call the LLM."""
    blocks: list[str] = []

    if conversation_summary:
        blocks.append(f"=== SUMMARY OF PREVIOUS CONVERSATION ===\n{conversation_summary}\n=== END SUMMARY ===")

    if attached_documents:
        titles = "\n".join(f"- {d.title}" + ("" if d.status == "ready" else f" ({d.status})") for d in attached_documents)
        blocks.append(f"Documents attached to this conversation (retrieval is limited to these):\n{titles}")

    if context_chunks:
        sources = "\n\n".join(
            f"[{i}] {c.document_title}{f' — page {c.page}' if c.page else ''}\n{c.content}"
            for i, c in enumerate(context_chunks, start=1)
        )
        blocks.append(f"=== SOURCES ===\n{sources}\n=== END SOURCES ===")
        blocks.append(f"User question: {query}")
    else:
        blocks.append(
            f"User question: {query}\n\n"
            "No relevant passages were found in the documents. Tell the user, and suggest "
            "attaching or uploading a document that covers this."
        )

    return await generate_chat_response(
        prompt="\n\n".join(blocks),
        history=conversation_history or [],
        system=ANSWER_SYSTEM_PROMPT,
    )


def build_citations(chunks: list[ChunkResponse], answer: str) -> list[dict]:
    """Numbered citation records stored on the assistant message. `n` matches the [n] markers in the answer."""
    cited = {int(n) for n in CITATION_RE.findall(answer)}
    return [
        {
            "n": i,
            "id": str(c.id),
            "document_id": str(c.document_id),
            "document_title": c.document_title,
            "chunk_index": c.chunk_index,
            "page": c.page,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "content": c.content,
            "score": c.score,
            "cited": i in cited,
        }
        for i, c in enumerate(chunks, start=1)
    ]


# ─── Conversation helpers ─────────────────────────────────────────────────────

def title_from_message(text: str, limit: int = 60) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


async def get_or_create_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID | None,
) -> Conversation:
    if conversation_id:
        conv = await db.get(Conversation, conversation_id)
        if conv:
            return conv
    conv = Conversation()
    db.add(conv)
    await db.flush()
    return conv


async def list_conversation_documents(db: AsyncSession, conversation_id: uuid.UUID) -> list[Document]:
    result = await db.execute(
        select(Document)
        .join(ConversationDocument, ConversationDocument.document_id == Document.id)
        .where(ConversationDocument.conversation_id == conversation_id)
        .order_by(ConversationDocument.added_at)
    )
    return list(result.scalars().all())


async def link_document(db: AsyncSession, conversation_id: uuid.UUID, document_id: uuid.UUID) -> None:
    exists = await db.get(ConversationDocument, (conversation_id, document_id))
    if not exists:
        db.add(ConversationDocument(conversation_id=conversation_id, document_id=document_id))
        await db.flush()


async def get_recent_history(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    window: int | None = None,
) -> list[dict]:
    """
    Fetch the last `window` messages from a conversation and format them
    as OpenAI-style message dicts for the LLM context.
    """
    _window = window or settings.CHAT_HISTORY_WINDOW

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(_window)
    )
    messages = list(reversed(result.scalars().all()))

    # Old [n] markers refer to old source lists — strip them so the model doesn't reuse them
    return [
        {"role": m.role, "content": CITATION_RE.sub("", m.content) if m.role == "assistant" else m.content}
        for m in messages
    ]


async def update_conversation_summary_if_needed(
    db: AsyncSession,
    conversation: Conversation,
) -> None:
    """
    Trigger summarization every `SUMMARY_TRIGGER_INTERVAL` messages (e.g. at 10, 20, 30...).
    Appends new key points to the existing summary rather than replacing it.
    """
    # Count total messages in this conversation
    count_result = await db.execute(
        select(func.count(Message.id)).where(Message.conversation_id == conversation.id)
    )
    total_messages = count_result.scalar_one() or 0

    interval = settings.SUMMARY_TRIGGER_INTERVAL
    last_count = conversation.last_summarized_count or 0

    # Trigger whenever we have reached or exceeded a new 10-message interval
    if total_messages >= last_count + interval:
        # Fetch the messages added since the last summary
        offset = last_count
        limit = total_messages - last_count
        new_msgs_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        new_msgs = new_msgs_result.scalars().all()
        if not new_msgs:
            return

        chat_transcript = "\n".join(
            f"{m.role.capitalize()}: {m.content}" for m in new_msgs
        )

        existing_summary = conversation.summary or "No previous summary."

        prompt = (
            "You are a conversation summarizer maintaining memory of an ongoing discussion.\n\n"
            f"PREVIOUS SUMMARY:\n{existing_summary}\n\n"
            f"NEW MESSAGES (last {len(new_msgs)} messages):\n{chat_transcript}\n\n"
            "TASK:\n"
            "Produce an updated chronological summary. Add on the key questions, topics, user preferences, "
            "and facts from the new messages to the existing knowledge. Do NOT discard prior information; "
            "synthesize them into a clear, cumulative summary."
        )

        new_summary = await generate_chat_response(prompt=prompt, history=[])
        conversation.summary = new_summary.strip()
        conversation.last_summarized_count = total_messages
        await db.commit()
