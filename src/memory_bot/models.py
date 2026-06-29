from __future__ import annotations

from pydantic import BaseModel


class Note(BaseModel):
    note_id: str
    text: str
    category: str
    created_at: str
    summary: str | None = None
    status: str | None = None
    due_at: str | None = None
