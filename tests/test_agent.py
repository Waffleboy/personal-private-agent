import boto3
import pytest
from moto import mock_aws
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
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
    agent = build_agent("anthropic:claude-sonnet-4-6")
    joined = _capture_instructions(agent, deps)
    assert "Asia/Singapore" in joined
    assert "2026-06-27T08:00:00+08:00" in joined


def test_system_prompt_includes_current_datetime(deps):
    # No timezone set on the fixture -> falls back to UTC, rendered with offset.
    agent = build_agent("anthropic:claude-sonnet-4-6")
    joined = _capture_instructions(agent, deps)
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


def test_mark_done_tool_completes_note(deps):
    from memory_bot.models import Note

    deps.store.put_note(1, Note(
        note_id="abc123", text="deploy prod", category="work log",
        created_at="2026-06-29T10:00:00Z", status="open",
    ))

    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("mark_done", {"note_id": "abc123"})]
            )
        return ModelResponse(parts=[TextPart("Marked done.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        run_message(agent, deps, "done with the deploy")
    assert deps.store.query_notes(1)[0].status == "done"


def test_mark_done_tool_unknown_id_reports_not_found(deps):
    from pydantic_ai.messages import ToolReturnPart

    from memory_bot.models import Note

    # A note exists, but with a different id than the one we mark done.
    deps.store.put_note(1, Note(
        note_id="abc123", text="deploy prod", category="work log",
        created_at="2026-06-29T10:00:00Z", status="open",
    ))

    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("mark_done", {"note_id": "nope"})]
            )
        return ModelResponse(parts=[TextPart("No such note.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        _, messages = run_message(agent, deps, "done with nope")

    returns = [
        p.content
        for m in messages
        for p in m.parts
        if isinstance(p, ToolReturnPart) and p.tool_name == "mark_done"
    ]
    assert returns, "expected a mark_done tool return"
    assert "nope" in returns[0]
    assert "no note" in returns[0].lower()
    # The existing note must be untouched.
    assert deps.store.query_notes(1)[0].status == "open"


def test_delete_note_tool_removes_note(deps):
    from memory_bot.models import Note

    deps.store.put_note(1, Note(
        note_id="abc123", text="deploy prod", category="work log",
        created_at="2026-06-29T10:00:00Z", status="open",
    ))

    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("delete_note", {"note_id": "abc123"})]
            )
        return ModelResponse(parts=[TextPart("Removed.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        run_message(agent, deps, "remove the deploy task")
    assert deps.store.query_notes(1) == []


def test_delete_note_tool_unknown_id_reports_not_found(deps):
    from pydantic_ai.messages import ToolReturnPart

    from memory_bot.models import Note

    deps.store.put_note(1, Note(
        note_id="abc123", text="deploy prod", category="work log",
        created_at="2026-06-29T10:00:00Z", status="open",
    ))

    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("delete_note", {"note_id": "nope"})]
            )
        return ModelResponse(parts=[TextPart("No such note.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(call)):
        _, messages = run_message(agent, deps, "remove nope")

    returns = [
        p.content
        for m in messages
        for p in m.parts
        if isinstance(p, ToolReturnPart) and p.tool_name == "delete_note"
    ]
    assert returns, "expected a delete_note tool return"
    assert "nope" in returns[0]
    assert "no note" in returns[0].lower()
    # The existing note must be untouched.
    assert deps.store.query_notes(1)[0].note_id == "abc123"


def _capture_instructions(agent, deps, text="hello", message_history=None):
    captured = []

    def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for m in messages:
            if isinstance(m, ModelRequest) and m.instructions:
                captured.append(m.instructions)
        return ModelResponse(parts=[TextPart("ok")])

    with agent.override(model=FunctionModel(call)):
        run_message(agent, deps, text, message_history=message_history)
    return "\n".join(captured)


def test_working_memory_injects_live_notes(deps):
    from memory_bot.models import Note

    deps.store.put_note(1, Note(
        note_id="b2c", text="deploy prod", category="work log",
        created_at="2026-06-29T10:00:00Z", status="open",
        due_at="2026-06-29T23:59:00+08:00",
    ))
    deps.store.put_note(1, Note(
        note_id="a3f", text="text mom tonight", category="family",
        created_at="2026-06-29T11:00:00Z",
    ))
    agent = build_agent("anthropic:claude-sonnet-4-6")
    prompt = _capture_instructions(agent, deps)
    assert "work log" in prompt
    assert "deploy prod" in prompt
    assert "2026-06-29T23:59:00+08:00" in prompt  # due date shown
    assert "b2c" in prompt  # note id shown
    assert "family" in prompt
    assert "text mom tonight" in prompt


def test_working_memory_lists_existing_categories(deps):
    from memory_bot.models import Note

    deps.store.put_note(1, Note(
        note_id="b2c", text="deploy prod", category="work",
        created_at="2026-06-29T10:00:00Z", status="open",
    ))
    deps.store.put_note(1, Note(
        note_id="a3f", text="text mom tonight", category="family",
        created_at="2026-06-29T11:00:00Z",
    ))
    agent = build_agent("anthropic:claude-sonnet-4-6")
    prompt = _capture_instructions(agent, deps)
    # The existing categories are surfaced up front to bias reuse (option C).
    assert "Existing categories: family, work" in prompt


def test_working_memory_excludes_done_notes(deps):
    from memory_bot.models import Note

    deps.store.put_note(1, Note(
        note_id="d1", text="old finished task", category="todo",
        created_at="2026-06-29T09:00:00Z", status="done",
    ))
    deps.store.put_note(1, Note(
        note_id="o1", text="still open task", category="todo",
        created_at="2026-06-29T10:00:00Z", status="open",
    ))
    agent = build_agent("anthropic:claude-sonnet-4-6")
    prompt = _capture_instructions(agent, deps)
    assert "still open task" in prompt
    assert "old finished task" not in prompt


def test_working_memory_empty_state(deps):
    agent = build_agent("anthropic:claude-sonnet-4-6")
    prompt = _capture_instructions(agent, deps)
    assert "No notes yet." in prompt


def test_worklog_note_visible_for_todo_query(deps):
    from memory_bot.models import Note

    # The original bug: note filed under "work log", user asks for to-dos.
    deps.store.put_note(1, Note(
        note_id="b2c", text="deploy prod tonight", category="work log",
        created_at="2026-06-29T22:34:00Z", status=None,
    ))
    agent = build_agent("anthropic:claude-sonnet-4-6")
    prompt = _capture_instructions(agent, deps, text="what's in my list to do")
    # The deploy item is in the model's context regardless of category name.
    assert "deploy prod tonight" in prompt
    assert "work log" in prompt


def test_working_memory_refreshes_across_turns(deps):
    """Regression for the transcript bug: a note saved in turn 1 must appear in
    the working-memory block on turn 2, when message_history is replayed.

    The working memory is registered with @agent.instructions, which pydantic-ai
    recomputes fresh on every request rather than baking into history. (A bare
    @agent.system_prompt would be frozen at turn 1's "No notes yet." state and
    replayed stale on turn 2 — exactly what the user saw.)
    """

    # Turn 1: user shares an item; the model files it via save_note.
    def turn1(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not any(
            isinstance(p, ToolCallPart)
            for m in messages
            for p in m.parts
        ):
            return ModelResponse(
                parts=[ToolCallPart("save_note", {
                    "text": "deploy prod tonight", "category": "work log",
                })]
            )
        return ModelResponse(parts=[TextPart("Filed under 'work log'.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(turn1)):
        _, history = run_message(agent, deps, "remind me to deploy prod tonight")

    assert deps.store.query_notes(1)[0].text == "deploy prod tonight"

    # Turn 2: replay history and capture the instructions the model now sees.
    prompt = _capture_instructions(
        agent, deps, text="what do I have to do?", message_history=history
    )
    assert "deploy prod tonight" in prompt, (
        "turn-2 working memory is stale; the saved note is not in context"
    )


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
