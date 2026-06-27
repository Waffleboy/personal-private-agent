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
    return Note(note_id=note_id, text=f"t-{note_id}", category=category,
                created_at=created_at, status=status)


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
