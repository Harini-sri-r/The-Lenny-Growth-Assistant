"""Session-scoped chat endpoints with persisted message history."""
from datetime import datetime, timezone

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.chat import ChatMessage, ChatSession, ChatUser
from app.schemas.chat import ChatRequest, ChatResponse, MessageOut, SessionCreate, SessionSummary
from app.services.container import get_rag_service
from app.services.rag import RAGService
from app.core.rag_diagnostics import request_id_context

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _require_session(db: Session, session_id: str, user_id: str) -> ChatSession:
    chat_session = db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id))
    if chat_session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return chat_session


@router.post("/sessions", response_model=SessionSummary, status_code=201)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    user = db.get(ChatUser, payload.user_id)
    if user is None:
        user = ChatUser(id=payload.user_id, display_name=payload.display_name)
        db.add(user)
    elif payload.display_name and user.display_name != payload.display_name:
        user.display_name = payload.display_name
    chat_session = ChatSession(user_id=payload.user_id)
    db.add(chat_session)
    db.commit()
    db.refresh(chat_session)
    return chat_session


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(user_id: str = Query(min_length=8, max_length=64), db: Session = Depends(get_db)):
    return list(db.scalars(select(ChatSession).where(ChatSession.user_id == user_id).order_by(ChatSession.updated_at.desc())).all())


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
def list_messages(session_id: str, user_id: str = Query(min_length=8, max_length=64), db: Session = Depends(get_db)):
    chat_session = _require_session(db, session_id, user_id)
    return list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == chat_session.id).order_by(ChatMessage.created_at, ChatMessage.id)).all())


@router.post("/sessions/{session_id}/messages", response_model=ChatResponse)
def send_message(session_id: str, payload: ChatRequest, request: Request, db: Session = Depends(get_db), rag: RAGService = Depends(get_rag_service)):
    chat_session = _require_session(db, session_id, payload.user_id)
    user_message = ChatMessage(session_id=session_id, role="user", content=payload.message.strip())
    db.add(user_message)
    if chat_session.title == "New conversation":
        chat_session.title = payload.message.strip()[:80]
    chat_session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user_message)

    request_id = getattr(request.state, "request_id", None)
    context_token = request_id_context.set(request_id) if request_id else None
    try:
        result = rag.answer(payload.message.strip())
    except Exception as exc:
        # Provider details can contain local paths or infrastructure information; keep them out of API output.
        logger.exception("Chat answer generation failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(status_code=503, detail="The answer service is unavailable. Check the configured LLM and embedding providers.") from exc
    finally:
        if context_token is not None:
            request_id_context.reset(context_token)

    assistant_message = ChatMessage(
        session_id=session_id, role="assistant", content=result.answer,
        sources=[source.__dict__ for source in result.sources], grounded=result.grounded,
    )
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    db.refresh(chat_session)
    return ChatResponse(session=chat_session, user_message=user_message, assistant_message=assistant_message)
