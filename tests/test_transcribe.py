import os

import pydantic_ai.models
from pydantic_ai.messages import BinaryContent, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from memory_bot.transcribe import build_transcriber, transcribe

pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
# The google provider needs an API key at Agent construction time; the model is
# overridden with a FunctionModel below so no real request is ever made.
os.environ.setdefault("GOOGLE_API_KEY", "test-key")


def test_transcribe_returns_stripped_text():
    seen = {}

    def call(messages, info: AgentInfo) -> ModelResponse:
        parts = [p for m in messages for p in getattr(m, "parts", [])]
        for p in parts:
            for item in (
                p.content if isinstance(getattr(p, "content", None), list) else []
            ):
                if isinstance(item, BinaryContent):
                    seen["media_type"] = item.media_type
                    seen["data"] = item.data
        return ModelResponse(parts=[TextPart("  buy milk tomorrow  ")])

    agent = build_transcriber("google:gemini-3-flash-preview")
    with agent.override(model=FunctionModel(call)):
        text = transcribe(
            "google:gemini-3-flash-preview",
            b"OGGAUDIO",
            "audio/ogg",
            agent=agent,
        )
    assert text == "buy milk tomorrow"
    assert seen["media_type"] == "audio/ogg"
    assert seen["data"] == b"OGGAUDIO"
