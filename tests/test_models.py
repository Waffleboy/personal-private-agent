from memory_bot.models import Note, UserContext


def test_note_minimal():
    n = Note(text="hi", category="idea", created_at="2026-06-27T00:00:00Z", note_id="abc")
    assert n.text == "hi"
    assert n.summary is None
    assert n.status is None


def test_user_context():
    ctx = UserContext(user_id=42)
    assert ctx.user_id == 42
