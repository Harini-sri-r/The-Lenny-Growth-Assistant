"""Validated HTTP schemas for chat sessions and messages."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SessionCreate(BaseModel):
    user_id: str = Field(min_length=8, max_length=64)
    display_name: str | None = Field(default=None, max_length=120)


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=8, max_length=64)
    message: str = Field(min_length=1, max_length=12000)

    @field_validator("message")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message cannot be blank")
        return value


class SourceOut(BaseModel):
    source_id: str
    title: str
    document_type: str
    source_path: str
    url: str | None
    chunk_id: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    session_id: str
    role: str
    content: str
    sources: list[SourceOut] = Field(default_factory=list)
    grounded: bool | None = Field(
        default=None,
        description="True means factual answer sentences carry citations mapped to retrieved sources; semantic entailment is not independently verified.",
    )
    created_at: datetime


class ChatResponse(BaseModel):
    session: SessionSummary
    user_message: MessageOut
    assistant_message: MessageOut


class ArtifactRequest(BaseModel):
    user_id: str = Field(min_length=8, max_length=64)
    session_id: str
    topic: str = Field(min_length=3, max_length=400)
    audience: str = Field(default="product managers and startup operators", max_length=300)
    artifact_format: Literal["markdown", "html"] = "markdown"

    @field_validator("topic")
    @classmethod
    def clean_topic(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Topic cannot be blank")
        return value


class ArtifactOut(BaseModel):
    id: str
    user_id: str
    session_id: str
    title: str
    artifact_format: str
    content: str
    sources: list[SourceOut]
    word_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
