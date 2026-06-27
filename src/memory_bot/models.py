from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


class Note(BaseModel):
    note_id: str
    text: str
    category: str
    created_at: str
    summary: str | None = None
    status: str | None = None


@dataclass
class UserContext:
    user_id: int
