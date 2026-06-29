from memory_bot.models import Note


def test_note_minimal():
    n = Note(
        text="hi", category="idea", created_at="2026-06-27T00:00:00Z", note_id="abc"
    )
    assert n.text == "hi"
    assert n.summary is None
    assert n.status is None
    assert n.due_at is None


def test_note_with_due_at():
    n = Note(
        text="finish report",
        category="todo",
        created_at="2026-06-27T00:00:00Z",
        note_id="abc",
        due_at="2026-06-30T00:00:00Z",
    )
    assert n.due_at == "2026-06-30T00:00:00Z"
