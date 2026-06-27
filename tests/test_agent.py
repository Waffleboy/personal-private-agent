import boto3
import pytest
from moto import mock_aws

from pydantic_ai.models.function import FunctionModel, AgentInfo
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart

from memory_bot.agent import build_agent, AgentDeps, run_message
from memory_bot.store import Store


@pytest.fixture
def deps():
    with mock_aws():
        res = boto3.resource("dynamodb", region_name="us-east-1")
        Store.create_table(res, "notes")
        store = Store("notes", dynamodb_resource=res)
        ids = iter(["id1", "id2", "id3"])
        yield AgentDeps(store=store, user_id=1,
                        now="2026-06-27T00:00:00Z", new_id=lambda: next(ids))


def test_save_note_tool_persists(deps):
    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart(
                "save_note", {"text": "read sdlc guide", "category": "todo"})])
        return ModelResponse(parts=[TextPart("Filed under todo.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        out = run_message(agent, deps, "read sdlc guide")
    assert "todo" in out.lower()
    saved = deps.store.query_notes(1)
    assert len(saved) == 1
    assert saved[0].category == "todo"
    assert saved[0].status == "open"  # todo gets open status


def test_list_notes_tool_returns_todos(deps):
    from memory_bot.models import Note
    deps.store.put_note(1, Note(note_id="x", text="task one", category="todo",
                                created_at="2026-06-27T01:00:00Z", status="open"))

    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart(
                "list_notes", {"category": "todo", "status": "open"})])
        return ModelResponse(parts=[TextPart("You have 1 todo: task one.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        out = run_message(agent, deps, "what's my todo log")
    assert "task one" in out
