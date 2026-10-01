from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


class Source(StrEnum):
    CHAT = "chat"
    DRAWING = "drawing"
    NEWS = "news"
    QUEST = "quest"


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"


class Event(BaseModel):
    """An immutable fact that happened. Never updated — corrections are new events."""

    model_config = {"frozen": True}

    id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Source
    modality: Modality
    content: str = Field(min_length=1)
    raw_uri: str | None = None
    salience: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def must_be_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return v
