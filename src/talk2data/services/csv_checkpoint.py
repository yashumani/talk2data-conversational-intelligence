"""Versioned serialization of bounded CSV sessions; capability tokens are hashed by RunStore."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from talk2data.domain.chat import DemoChatResponse
from talk2data.domain.models import InterpretationResult
from talk2data.services.csv_import import CsvDataset


class SavedInterpretation(BaseModel):
    dataset: CsvDataset
    question: str
    as_of: datetime
    snapshot_id: str
    interpretation: InterpretationResult | None = None
    model: str | None = None


class CsvCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    user_id: str
    expires_wall: float
    conversation_id: UUID
    dataset: CsvDataset | None
    history: dict[str, SavedInterpretation]
    last_response: DemoChatResponse | None
    language_questions: int

    def payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
