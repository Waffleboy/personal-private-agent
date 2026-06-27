from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class IncomingMessage:
    user_id: int
    chat_id: int
    text: str


def parse_update(update: dict) -> IncomingMessage | None:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    text = msg.get("text")
    frm = msg.get("from") or {}
    chat = msg.get("chat") or {}
    if not text or "id" not in frm or "id" not in chat:
        return None
    return IncomingMessage(user_id=frm["id"], chat_id=chat["id"], text=text)


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
