from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RelatedItem(BaseModel):
    id: int | None = None
    name: str
    api_detail_url: str | None = None


class Character(BaseModel):
    id: int
    name: str
    real_name: str | None = None
    deck: str | None = None
    description: str | None = None
    image_url: str | None = None
    publisher: RelatedItem | None = None
    origin: RelatedItem | None = None
    powers: list[RelatedItem] = Field(default_factory=list)
    teams: list[RelatedItem] = Field(default_factory=list)
    first_appeared_in_issue: RelatedItem | None = None
    count_of_issue_appearances: int | None = None
    api_detail_url: str | None = None


class CharacterPage(BaseModel):
    results: list[Character]
    offset: int
    limit: int
    total: int
    has_more: bool
    relations_complete: bool = True
    next_offset: int | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    spoiler_level: str = "NONE"
    language: Literal["pt-BR", "en"] = "pt-BR"
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    conversation_id: UUID | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[str] = Field(default_factory=list)


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
