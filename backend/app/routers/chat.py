import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from app.database import get_db
from app.models import Conversation, ConversationDocument, Document, Message
from app.schemas import (
    ConversationCreate, ConversationUpdate, ConversationResponse, LinkDocumentsRequest,
    DocumentResponse, MessageCreate, ChatResponse, MessageResponse,
)
from app.routers.documents import document_responses, read_upload, title_from_filename
from app.services.ingestion import checksum_of, create_document, find_duplicate, schedule_processing
from app.services.rag import (
    similarity_search,
    retrieve_for_conversation,
    generate_answer,
    build_citations,
    title_from_message,
    get_or_create_conversation,
    get_recent_history,
    list_conversation_documents,
    link_document,
    update_conversation_summary_if_needed,
)
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/chat", tags=["Chat"])

DEFAULT_TITLE = "New Conversation"


async def _get_conversation_or_404(db: AsyncSession, conversation_id: uuid.UUID) -> Conversation:
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


async def _conversation_responses(db: AsyncSession, convs: list[Conversation]) -> list[ConversationResponse]:
    if not convs:
        return []
    ids = [c.id for c in convs]
    doc_counts = dict((await db.execute(
        select(ConversationDocument.conversation_id, func.count())
        .where(ConversationDocument.conversation_id.in_(ids))
        .group_by(ConversationDocument.conversation_id)
    )).all())
    msg_counts = dict((await db.execute(
        select(Message.conversation_id, func.count())
        .where(Message.conversation_id.in_(ids))
        .group_by(Message.conversation_id)
    )).all())
    return [
        ConversationResponse.model_validate(c).model_copy(update={
            "document_count": doc_counts.get(c.id, 0),
            "message_count": msg_counts.get(c.id, 0),
        })
        for c in convs
    ]


# ─── Conversations ────────────────────────────────────────────────────────────

@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(title=payload.title)
    db.add(conv)
    await db.flush()
    for doc_id in payload.document_ids:
        if await db.get(Document, doc_id):
            await link_document(db, conv.id, doc_id)
    await db.commit()
    await db.refresh(conv)
    return (await _conversation_responses(db, [conv]))[0]


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(100)
    )
    return await _conversation_responses(db, list(result.scalars().all()))


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    conv = await _get_conversation_or_404(db, conversation_id)
    return (await _conversation_responses(db, [conv]))[0]


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
):
    conv = await _get_conversation_or_404(db, conversation_id)
    conv.title = payload.title.strip()
    await db.commit()
    await db.refresh(conv)
    return (await _conversation_responses(db, [conv]))[0]


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Deletes the conversation and its messages. Attached documents stay in the Documents tab."""
    conv = await _get_conversation_or_404(db, conversation_id)
    await db.execute(delete(Conversation).where(Conversation.id == conv.id))
    await db.commit()


# ─── Conversation documents ───────────────────────────────────────────────────

@router.get("/conversations/{conversation_id}/documents", response_model=list[DocumentResponse])
async def get_conversation_documents(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_conversation_or_404(db, conversation_id)
    return await document_responses(db, await list_conversation_documents(db, conversation_id))


@router.post("/conversations/{conversation_id}/documents", response_model=list[DocumentResponse])
async def link_conversation_documents(
    conversation_id: uuid.UUID,
    payload: LinkDocumentsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Ground the conversation in existing documents (e.g. picked from the library)."""
    await _get_conversation_or_404(db, conversation_id)
    found = (await db.execute(select(Document.id).where(Document.id.in_(payload.document_ids)))).scalars().all()
    missing = set(payload.document_ids) - set(found)
    if missing:
        raise HTTPException(status_code=404, detail=f"Documents not found: {', '.join(map(str, missing))}")
    for doc_id in payload.document_ids:
        await link_document(db, conversation_id, doc_id)
    await db.commit()
    return await document_responses(db, await list_conversation_documents(db, conversation_id))


@router.post("/conversations/{conversation_id}/attachments", response_model=DocumentResponse, status_code=201)
async def attach_file(
    conversation_id: uuid.UUID,
    response: Response,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file directly into a conversation. Identical files already ingested are reused, not re-embedded."""
    await _get_conversation_or_404(db, conversation_id)
    raw, filename = await read_upload(file)

    doc = await find_duplicate(db, checksum_of(raw))
    if doc:
        response.status_code = 200
        await link_document(db, conversation_id, doc.id)
        await db.commit()
        return (await document_responses(db, [doc]))[0].model_copy(update={"duplicate": True})

    doc = await create_document(db, raw=raw, filename=filename, title=title_from_filename(filename), origin="chat")
    await link_document(db, conversation_id, doc.id)
    await db.commit()
    schedule_processing(doc.id)
    return (await document_responses(db, [doc]))[0]


@router.delete("/conversations/{conversation_id}/documents/{document_id}", status_code=204)
async def unlink_conversation_document(
    conversation_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Detach a document from the conversation (the document itself is kept)."""
    await db.execute(
        delete(ConversationDocument).where(
            ConversationDocument.conversation_id == conversation_id,
            ConversationDocument.document_id == document_id,
        )
    )
    await db.commit()


# ─── Messages ─────────────────────────────────────────────────────────────────

@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_messages(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return result.scalars().all()


@router.post("/conversations/{conversation_id}/messages", response_model=ChatResponse)
async def send_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Full RAG chat flow:
      1. Fetch recent conversation history (last N messages)
      2. Save user message
      3. Retrieve: the conversation's attached documents if any, else the library
      4. Build grounded prompt (numbered sources + history + summary) → LLM
      5. Save assistant response with citation records
    """
    conv = await _get_conversation_or_404(db, conversation_id)

    # Step 1: Fetch conversation history BEFORE adding the new message
    history = await get_recent_history(db, conv.id, window=settings.CHAT_HISTORY_WINDOW)

    # Step 2: Save user message (first message names the conversation)
    user_msg = Message(conversation_id=conv.id, role="user", content=payload.content)
    db.add(user_msg)
    if not history and conv.title == DEFAULT_TITLE:
        conv.title = title_from_message(payload.content)
    await db.flush()

    # Step 3: Retrieval, scoped to this conversation's documents when present
    chunks, attached = await retrieve_for_conversation(db, conv.id, payload.content, history)

    # Step 4: Generate answer
    answer = await generate_answer(
        query=payload.content,
        context_chunks=chunks,
        conversation_history=history,
        conversation_summary=conv.summary,
        attached_documents=attached,
    )

    # Step 5: Save assistant message with citations; bump conversation recency
    assistant_msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=answer,
        sources=build_citations(chunks, answer),
    )
    db.add(assistant_msg)
    conv.updated_at = func.now()
    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(assistant_msg)
    await db.refresh(conv)

    # Step 6: Incrementally update conversation summary every N messages
    await update_conversation_summary_if_needed(db, conv)

    return ChatResponse(
        conversation_id=conv.id,
        conversation_title=conv.title,
        user_message=MessageResponse.model_validate(user_msg),
        assistant_message=MessageResponse.model_validate(assistant_msg),
        sources=chunks,
    )


@router.post("/ask", response_model=ChatResponse)
async def ask_without_conversation(
    payload: MessageCreate,
    db: AsyncSession = Depends(get_db),
):
    """One-shot RAG query over the library (no history)."""
    conv = await get_or_create_conversation(db, None)
    conv.title = title_from_message(payload.content)

    user_msg = Message(conversation_id=conv.id, role="user", content=payload.content)
    db.add(user_msg)
    await db.flush()

    chunks = await similarity_search(db, payload.content)
    answer = await generate_answer(query=payload.content, context_chunks=chunks)

    assistant_msg = Message(
        conversation_id=conv.id,
        role="assistant",
        content=answer,
        sources=build_citations(chunks, answer),
    )
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(assistant_msg)

    return ChatResponse(
        conversation_id=conv.id,
        conversation_title=conv.title,
        user_message=MessageResponse.model_validate(user_msg),
        assistant_message=MessageResponse.model_validate(assistant_msg),
        sources=chunks,
    )
