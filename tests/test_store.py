import boto3
import pytest
from moto import mock_aws

from memory_bot.models import Note
from memory_bot.store import Store


@pytest.fixture
def store():
    with mock_aws():
        res = boto3.resource("dynamodb", region_name="us-east-1")
        Store.create_table(res, "notes")
        yield Store("notes", dynamodb_resource=res)


def _note(note_id, category, created_at, status=None):
    return Note(
        note_id=note_id,
        text=f"t-{note_id}",
        category=category,
        created_at=created_at,
        status=status,
    )


def test_put_and_query_all(store):
    store.put_note(1, _note("a", "todo", "2026-06-27T01:00:00Z"))
    store.put_note(1, _note("b", "idea", "2026-06-27T02:00:00Z"))
    notes = store.query_notes(1)
    assert [n.note_id for n in notes] == ["b", "a"]  # newest first


def test_query_filters_by_category_and_status(store):
    store.put_note(1, _note("a", "todo", "2026-06-27T01:00:00Z", status="open"))
    store.put_note(1, _note("b", "todo", "2026-06-27T02:00:00Z", status="done"))
    store.put_note(1, _note("c", "idea", "2026-06-27T03:00:00Z"))
    todos = store.query_notes(1, category="todo", status="open")
    assert [n.note_id for n in todos] == ["a"]


def test_user_scoping(store):
    store.put_note(1, _note("a", "todo", "2026-06-27T01:00:00Z"))
    store.put_note(2, _note("b", "todo", "2026-06-27T02:00:00Z"))
    assert [n.note_id for n in store.query_notes(1)] == ["a"]
    assert [n.note_id for n in store.query_notes(2)] == ["b"]


def test_put_and_query_preserves_due_at(store):
    store.put_note(
        1,
        Note(
            note_id="a",
            text="finish report",
            category="todo",
            created_at="2026-06-27T01:00:00Z",
            status="open",
            due_at="2026-06-30T00:00:00Z",
        ),
    )
    store.put_note(1, _note("b", "idea", "2026-06-27T02:00:00Z"))
    notes = {n.note_id: n for n in store.query_notes(1)}
    assert notes["a"].due_at == "2026-06-30T00:00:00Z"
    assert notes["b"].due_at is None


def test_get_timezone_defaults_to_none(store):
    assert store.get_timezone(1) is None


def test_set_and_get_timezone(store):
    store.set_timezone(1, "Asia/Singapore")
    assert store.get_timezone(1) == "Asia/Singapore"


def test_timezone_is_user_scoped(store):
    store.set_timezone(1, "Asia/Singapore")
    assert store.get_timezone(2) is None


def test_settings_item_excluded_from_notes(store):
    # The settings item shares the user's pk; it must not be returned as a Note.
    store.set_timezone(1, "Asia/Singapore")
    store.put_note(1, _note("a", "todo", "2026-06-27T01:00:00Z"))
    notes = store.query_notes(1)
    assert [n.note_id for n in notes] == ["a"]


def _note_large(note_id, category, created_at, text_size=10000, status=None):
    """Helper to create a note with large text to exceed DynamoDB 1MB page limit."""
    large_text = "x" * text_size
    return Note(
        note_id=note_id,
        text=large_text,
        category=category,
        created_at=created_at,
        status=status,
    )


def test_pagination_with_large_notes(store):
    """Test that query_notes correctly handles pagination across 1MB DynamoDB pages."""
    # Insert 120 notes with ~10KB text each => ~1.2MB total, exceeds 1 page
    for i in range(120):
        ts = f"2026-06-27T{(i // 60):02d}:{(i % 60):02d}:00Z"
        store.put_note(1, _note_large(f"note-{i:03d}", "bulk", ts, text_size=10000))

    # Verify all notes are returned (not truncated at 1MB boundary)
    notes = store.query_notes(1)
    assert len(notes) == 120, f"Expected 120 notes but got {len(notes)}"

    # Verify newest-first ordering is maintained across pages
    note_ids = [n.note_id for n in notes]
    assert note_ids == [f"note-{i:03d}" for i in range(119, -1, -1)]

    # Verify category filter works across pages
    filtered = store.query_notes(1, category="bulk")
    assert len(filtered) == 120


def test_history_defaults_to_empty(store):
    assert store.get_history(1) == []


def test_history_round_trip(store):
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )

    msgs = [
        ModelRequest(parts=[UserPromptPart(content="hi")]),
        ModelResponse(parts=[TextPart(content="hello")]),
    ]
    store.save_history(1, msgs)
    loaded = store.get_history(1)
    assert len(loaded) == 2
    assert loaded[0].parts[0].content == "hi"
    assert loaded[1].parts[0].content == "hello"


def test_history_is_user_scoped(store):
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    store.save_history(1, [ModelRequest(parts=[UserPromptPart(content="hi")])])
    assert store.get_history(2) == []


def test_corrupt_history_returns_empty(store):
    # Write a garbage blob directly under the history key.
    store._table.put_item(
        Item={"pk": store._pk(1), "sk": "history", "messages": "not-valid-json{"}
    )
    assert store.get_history(1) == []


def test_clear_history_deletes(store):
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    store.save_history(1, [ModelRequest(parts=[UserPromptPart(content="hi")])])
    store.clear_history(1)
    assert store.get_history(1) == []


def test_history_item_excluded_from_notes(store):
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    store.save_history(1, [ModelRequest(parts=[UserPromptPart(content="hi")])])
    store.put_note(1, _note("a", "todo", "2026-06-27T01:00:00Z"))
    assert [n.note_id for n in store.query_notes(1)] == ["a"]


def test_mark_done_sets_status(store):
    store.put_note(1, Note(
        note_id="abc123", text="deploy prod", category="work log",
        created_at="2026-06-29T10:00:00Z", status="open",
    ))
    updated = store.mark_done(1, "abc123")
    assert updated is True
    note = store.query_notes(1)[0]
    assert note.status == "done"


def test_mark_done_unknown_id_returns_false(store):
    assert store.mark_done(1, "nope") is False


def test_mark_done_finds_note_on_later_page(store):
    """Regression guard: mark_done must paginate, not just read page 1.

    Insert ~120 notes of ~10KB each (>1MB total) so they span multiple
    DynamoDB query pages. mark_done scans in ascending sort-key order, so a
    note with one of the LATEST timestamps (highest index) lives on a later
    page; a single non-paginating query would miss it. This test fails against
    a single-query implementation and passes against the paginating one.
    """
    for i in range(120):
        ts = f"2026-06-27T{(i // 60):02d}:{(i % 60):02d}:00Z"
        store.put_note(1, _note_large(f"note-{i:03d}", "bulk", ts, text_size=10000))

    # Latest-inserted note: highest sort key -> on a later page of mark_done's
    # ascending query, forcing its LastEvaluatedKey loop to actually advance.
    target_id = "note-119"
    assert store.mark_done(1, target_id) is True

    notes = {n.note_id: n for n in store.query_notes(1)}
    assert notes[target_id].status == "done"
    # Every other note is untouched.
    for note_id, note in notes.items():
        if note_id != target_id:
            assert note.status is None
