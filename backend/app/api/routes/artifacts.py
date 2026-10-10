"""Grounded Ship 30 for 30 essay generation and persisted artifact listing."""
import re
from html import unescape
from html.parser import HTMLParser

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.chat import _require_session
from app.database.session import get_db
from app.models.chat import ChatArtifact
from app.schemas.chat import ArtifactOut, ArtifactRequest
from app.services.container import get_claude_research_agent
from app.agents.lenny_agent import ClaudeResearchAgent, ship30_system_prompt

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


class _HTMLWordCounter(HTMLParser):
    """Count visible HTML text, excluding style and script blocks."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"style", "script"}:
            self.ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"style", "script"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)


def _artifact_word_count(content: str, artifact_format: str) -> int:
    if artifact_format == "html":
        parser = _HTMLWordCounter()
        parser.feed(content)
        content = " ".join(parser.parts)
    else:
        content = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)
        content = re.sub(r"`[^`]*`", " ", content)
        content = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", content)
        content = re.sub(r"[#*_>`~]", " ", content)
    return len(re.findall(r"\b[\w'-]+\b", unescape(content)))


@router.post("/ship30", response_model=ArtifactOut, status_code=201)
def generate_ship30(payload: ArtifactRequest, db: Session = Depends(get_db), agent: ClaudeResearchAgent = Depends(get_claude_research_agent)):
    _require_session(db, payload.session_id, payload.user_id)
    format_instruction = "Markdown" if payload.artifact_format == "markdown" else "self-contained HTML with inline CSS and no JavaScript or remote resources"
    prompt = (
        f"Write a Ship 30 for 30 essay about: {payload.topic}\n"
        f"Intended audience: {payload.audience}\nRequested output: {format_instruction}. "
        "Target approximately 1,250 words. Search the transcript knowledge tool before drafting."
    )
    answer = agent.answer(prompt, system_prompt=ship30_system_prompt())
    if not answer.grounded or not answer.sources:
        raise HTTPException(status_code=422, detail="The transcript library did not return sufficient evidence for this essay.")
    word_count = _artifact_word_count(answer.answer, payload.artifact_format)
    title_match = re.search(r"(?m)^#\s+(.+)$", answer.answer)
    title = title_match.group(1).strip() if title_match else payload.topic[:240]
    artifact = ChatArtifact(
        user_id=payload.user_id, session_id=payload.session_id, title=title,
        artifact_format=payload.artifact_format, content=answer.answer,
        sources=[source.__dict__ for source in answer.sources], word_count=word_count,
    )
    db.add(artifact)
    db.commit()
    db.refresh(artifact)
    return artifact


@router.get("", response_model=list[ArtifactOut])
def list_artifacts(user_id: str = Query(min_length=8, max_length=64), db: Session = Depends(get_db)):
    return list(db.scalars(select(ChatArtifact).where(ChatArtifact.user_id == user_id).order_by(ChatArtifact.created_at.desc())).all())
