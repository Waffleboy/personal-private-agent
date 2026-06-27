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


def test_distinct_categories(store):
    store.put_note(1, _note("a", "todo", "2026-06-27T01:00:00Z"))
    store.put_note(1, _note("b", "todo", "2026-06-27T02:00:00Z"))
    store.put_note(1, _note("c", "idea", "2026-06-27T03:00:00Z"))
    assert sorted(store.distinct_categories(1)) == ["idea", "todo"]


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
