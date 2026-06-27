import json

from memory_bot.telegram import IncomingMessage, parse_update, send_message


def test_parse_update_extracts_message():
    update = {
        "update_id": 1,
        "message": {"from": {"id": 111}, "chat": {"id": 222}, "text": "hello"},
    }
    msg = parse_update(update)
    assert msg == IncomingMessage(user_id=111, chat_id=222, text="hello")


def test_parse_update_ignores_non_text():
    assert parse_update({"update_id": 1}) is None
    assert parse_update({"message": {"from": {"id": 1}, "chat": {"id": 2}}}) is None


def test_send_message_posts_to_telegram():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())

        class R:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R()

    send_message("TOK", 222, "hi there", urlopen=fake_urlopen)
    assert "botTOK/sendMessage" in captured["url"]
    assert captured["body"] == {"chat_id": 222, "text": "hi there"}
