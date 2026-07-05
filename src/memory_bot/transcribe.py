from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent

TRANSCRIBE_PROMPT = (
    "Transcribe this audio verbatim into text. Output only the transcript, "
    "with no commentary, labels, or quotation marks. If there is no speech, "
    "output nothing."
)


def build_transcriber(model: str) -> Agent:
    return Agent(model, instructions=TRANSCRIBE_PROMPT)


def transcribe(
    model: str,
    audio_bytes: bytes,
    mime_type: str,
    *,
    agent: Agent | None = None,
) -> str:
    """Transcribe audio bytes to text with a one-shot Gemini call."""
    agent = agent or build_transcriber(model)
    result = agent.run_sync(
        [BinaryContent(data=audio_bytes, media_type=mime_type)]
    )
    return (result.output or "").strip()
