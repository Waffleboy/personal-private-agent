import json

from memory_bot.telegram import (
    IncomingMessage,
    parse_update,
    send_message,
)


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


def test_parse_update_voice_note():
    update = {
        "update_id": 1,
        "message": {
            "from": {"id": 111},
            "chat": {"id": 222},
            "voice": {"file_id": "AwAC123", "duration": 7, "mime_type": "audio/ogg"},
        },
    }
    msg = parse_update(update)
    assert msg.user_id == 111
    assert msg.chat_id == 222
    assert msg.text is None
    assert msg.voice.file_id == "AwAC123"
    assert msg.voice.duration == 7
    assert msg.voice.mime_type == "audio/ogg"


def test_parse_update_audio_file():
    update = {
        "message": {
            "from": {"id": 1},
            "chat": {"id": 2},
            "audio": {"file_id": "aud9", "duration": 30, "mime_type": "audio/mpeg"},
        },
    }
    msg = parse_update(update)
    assert msg.voice.file_id == "aud9"
    assert msg.voice.mime_type == "audio/mpeg"


def test_parse_update_voice_without_mime_defaults_to_ogg():
    update = {
        "message": {
            "from": {"id": 1},
            "chat": {"id": 2},
            "voice": {"file_id": "v1", "duration": 3},
        },
    }
    msg = parse_update(update)
    assert msg.voice.mime_type == "audio/ogg"


def test_parse_update_text_still_works():
    update = {
        "message": {"from": {"id": 111}, "chat": {"id": 222}, "text": "hello"},
    }
    msg = parse_update(update)
    assert msg == IncomingMessage(user_id=111, chat_id=222, text="hello")


def test_parse_update_neither_text_nor_voice_is_none():
    update = {"message": {"from": {"id": 1}, "chat": {"id": 2}}}
    assert parse_update(update) is None


def test_download_file_two_step_fetch():
    from memory_bot.telegram import download_file

    calls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        calls.append(url)

        class R:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return self._payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        if "getFile" in url:
            return R(b'{"ok": true, "result": {"file_path": "voice/file_7.oga"}}')
        return R(b"RAW_AUDIO_BYTES")

    data = download_file("TOK", "AwAC123", urlopen=fake_urlopen)
    assert data == b"RAW_AUDIO_BYTES"
    assert "botTOK/getFile" in calls[0]
    assert "file_id=AwAC123" in calls[0]
    assert calls[1].endswith("file/botTOK/voice/file_7.oga")


def test_download_file_raises_on_not_ok_response():
    from memory_bot.telegram import download_file

    def fake_urlopen(req, timeout=None):
        class R:
            def read(self):
                return b'{"ok": false, "description": "file not found"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R()

    try:
        download_file("TOK", "bad-id", urlopen=fake_urlopen)
    except RuntimeError as exc:
        assert "file not found" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on ok:false response")


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
