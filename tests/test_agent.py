import boto3
import pytest
from moto import mock_aws
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from memory_bot.agent import AgentDeps, build_agent, run_message
from memory_bot.store import Store


@pytest.fixture
def deps():
    with mock_aws():
        res = boto3.resource("dynamodb", region_name="us-east-1")
        Store.create_table(res, "notes")
        store = Store("notes", dynamodb_resource=res)
        ids = iter(["id1", "id2", "id3"])
        yield AgentDeps(
            store=store, user_id=1, now="2026-06-27T00:00:00Z", new_id=lambda: next(ids)
        )


def test_save_note_tool_persists(deps):
    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "save_note", {"text": "read sdlc guide", "category": "todo"}
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("Filed under todo.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        out, _ = run_message(agent, deps, "read sdlc guide")
    assert "todo" in out.lower()
    saved = deps.store.query_notes(1)
    assert len(saved) == 1
    assert saved[0].category == "todo"
    assert saved[0].status == "open"  # todo gets open status


def test_save_note_tool_persists_due_at(deps):
    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "save_note",
                        {
                            "text": "finish report",
                            "category": "todo",
                            "due_at": "2026-06-28T00:00:00Z",
                        },
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("Filed under todo.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        run_message(agent, deps, "finish report due tomorrow")
    saved = deps.store.query_notes(1)
    assert len(saved) == 1
    assert saved[0].due_at == "2026-06-28T00:00:00Z"


def test_set_timezone_tool_persists(deps):
    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("set_timezone", {"tz": "Asia/Singapore"})]
            )
        return ModelResponse(parts=[TextPart("Timezone set to Asia/Singapore.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        run_message(agent, deps, "set my timezone to singapore")
    assert deps.store.get_timezone(1) == "Asia/Singapore"


def test_set_timezone_tool_rejects_invalid(deps):
    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("set_timezone", {"tz": "Mars/Olympus"})]
            )
        return ModelResponse(parts=[TextPart("Sorry, that timezone is invalid.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        run_message(agent, deps, "set my timezone to mars")
    assert deps.store.get_timezone(1) is None


def test_system_prompt_uses_user_timezone(deps):
    # 2026-06-27T00:00:00Z is 08:00 the same day in Asia/Singapore (+08:00).
    deps.store.set_timezone(1, "Asia/Singapore")
    captured = []

    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for m in messages:
            if isinstance(m, ModelRequest):
                for part in m.parts:
                    if isinstance(part, SystemPromptPart):
                        captured.append(part.content)
        return ModelResponse(parts=[TextPart("ok")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        run_message(agent, deps, "hello")
    joined = "\n".join(captured)
    assert "Asia/Singapore" in joined
    assert "2026-06-27T08:00:00+08:00" in joined


def test_system_prompt_includes_current_datetime(deps):
    # No timezone set on the fixture -> falls back to UTC, rendered with offset.
    captured = []

    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for m in messages:
            if isinstance(m, ModelRequest):
                for part in m.parts:
                    if isinstance(part, SystemPromptPart):
                        captured.append(part.content)
        return ModelResponse(parts=[TextPart("ok")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        run_message(agent, deps, "hello")
    joined = "\n".join(captured)
    assert "2026-06-27T00:00:00+00:00" in joined


def test_list_notes_tool_returns_todos(deps):
    from memory_bot.models import Note

    deps.store.put_note(
        1,
        Note(
            note_id="x",
            text="task one",
            category="todo",
            created_at="2026-06-27T01:00:00Z",
            status="open",
        ),
    )

    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart("list_notes", {"category": "todo", "status": "open"})
                ]
            )
        return ModelResponse(parts=[TextPart("You have 1 todo: task one.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        out, _ = run_message(agent, deps, "what's my todo log")
    assert "task one" in out


def _req(text):
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _resp(text):
    from pydantic_ai.messages import ModelResponse, TextPart
    return ModelResponse(parts=[TextPart(content=text)])


def _tool_return(name):
    from pydantic_ai.messages import ModelRequest, ToolReturnPart
    return ModelRequest(
        parts=[ToolReturnPart(tool_name=name, content="ok", tool_call_id="c1")]
    )


def test_trim_keeps_last_n_exchanges():
    from memory_bot.agent import trim_history

    msgs = []
    for i in range(4):
        msgs.append(_req(f"q{i}"))
        msgs.append(_resp(f"a{i}"))
    trimmed = trim_history(msgs, 2)
    # Last 2 exchanges => q2,a2,q3,a3
    texts = [p.content for m in trimmed for p in m.parts]
    assert texts == ["q2", "a2", "q3", "a3"]


def test_trim_keeps_tool_messages_with_exchange():
    from memory_bot.agent import trim_history

    msgs = [
        _req("q0"), _resp("call"), _tool_return("save_note"), _resp("a0"),
        _req("q1"), _resp("a1"),
    ]
    trimmed = trim_history(msgs, 1)
    # Keep only the last exchange (q1,a1); the q0 exchange + its tool msgs drop.
    texts = [p.content for m in trimmed for p in m.parts]
    assert texts == ["q1", "a1"]


def test_trim_starts_on_request_boundary():
    from pydantic_ai.messages import ModelRequest

    from memory_bot.agent import trim_history

    msgs = [
        _req("q0"), _resp("call"), _tool_return("save_note"), _resp("a0"),
        _req("q1"), _resp("a1"),
    ]
    trimmed = trim_history(msgs, 2)
    # Both exchanges kept; first element must be the q0 user request, never a
    # dangling tool-return.
    assert isinstance(trimmed[0], ModelRequest)
    assert any(
        getattr(p, "part_kind", None) == "user-prompt" for p in trimmed[0].parts
    )


def test_trim_zero_returns_empty():
    from memory_bot.agent import trim_history

    msgs = [_req("q0"), _resp("a0")]
    assert trim_history(msgs, 0) == []


def test_trim_fewer_than_n_returns_all():
    from memory_bot.agent import trim_history

    msgs = [_req("q0"), _resp("a0")]
    assert trim_history(msgs, 10) == msgs
