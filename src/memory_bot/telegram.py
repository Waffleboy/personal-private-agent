from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceMeta:
    file_id: str
    duration: int
    mime_type: str


@dataclass(frozen=True)
class IncomingMessage:
    user_id: int
    chat_id: int
    text: str | None
    voice: VoiceMeta | None = None


def parse_update(update: dict) -> IncomingMessage | None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    frm = msg.get("from") or {}
    chat = msg.get("chat") or {}
    if "id" not in frm or "id" not in chat:
        return None
    user_id = frm["id"]
    chat_id = chat["id"]

    audio = msg.get("voice") or msg.get("audio")
    if audio and audio.get("file_id"):
        voice = VoiceMeta(
            file_id=audio["file_id"],
            duration=int(audio.get("duration", 0)),
            mime_type=audio.get("mime_type") or "audio/ogg",
        )
        return IncomingMessage(
            user_id=user_id, chat_id=chat_id, text=None, voice=voice
        )

    text = msg.get("text")
    if not text:
        return None
    return IncomingMessage(user_id=user_id, chat_id=chat_id, text=text)


def send_message(
    token: str, chat_id: int, text: str, *, urlopen=urllib.request.urlopen
) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urlopen(req, timeout=10) as resp:
        resp.read()


def download_file(
    token: str, file_id: str, *, urlopen=urllib.request.urlopen
) -> bytes:
    """Fetch a Telegram file's bytes via the two-step getFile + download flow."""
    get_url = (
        f"https://api.telegram.org/bot{token}/getFile"
        f"?file_id={urllib.parse.quote(file_id)}"
    )
    with urlopen(get_url, timeout=10) as resp:
        meta = json.loads(resp.read().decode())
    if not meta.get("ok"):
        raise RuntimeError(f"Telegram getFile failed: {meta.get('description', meta)}")
    file_path = meta["result"]["file_path"]
    dl_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    with urlopen(dl_url, timeout=20) as resp:
        return resp.read()
