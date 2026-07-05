from __future__ import annotations

import hmac
import json
import logging
import os
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from functools import partial

from memory_bot.agent import AgentDeps, build_agent, run_message, trim_history
from memory_bot.config import load_settings
from memory_bot.store import Store
from memory_bot.telegram import download_file, parse_update, send_message
from memory_bot.transcribe import build_transcriber, transcribe

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_duration(seconds: int) -> str:
    """Human-friendly cap, e.g. 120 -> '2 min', 90 -> '1 min 30 sec', 45 -> '45 sec'."""
    if seconds < 60:
        return f"{seconds} sec"
    minutes, rem = divmod(seconds, 60)
    if rem == 0:
        return f"{minutes} min"
    return f"{minutes} min {rem} sec"


def handle(
    event,
    settings,
    store,
    agent,
    *,
    send=send_message,
    now: Callable[[], str] = _utcnow,
    new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:12],
    download=download_file,
    transcriber=transcribe,
) -> dict:
    # Verify webhook secret token if configured
    if settings.telegram_secret:
        headers = event.get("headers") or {}
        token = headers.get("x-telegram-bot-api-secret-token", "")
        if not hmac.compare_digest(token, settings.telegram_secret):
            logger.info("webhook secret verification failed")
            return {"statusCode": 200}

    msg = None
    try:
        body = event.get("body")
        update = json.loads(body) if isinstance(body, str) else (body or {})
        msg = parse_update(update)
        if msg is None:
            return {"statusCode": 200}
        if msg.user_id not in settings.allowed_users:
            logger.info("ignoring unauthorized user %s", msg.user_id)
            return {"statusCode": 200}

        if msg.voice is not None:
            if msg.voice.duration > settings.voice_max_seconds:
                send(
                    settings.telegram_token,
                    msg.chat_id,
                    "🎙️ That voice note is too long (max "
                    f"{_format_duration(settings.voice_max_seconds)}). "
                    "Please send it in shorter chunks.",
                )
                return {"statusCode": 200}
            try:
                audio = download(settings.telegram_token, msg.voice.file_id)
                transcript = transcriber(
                    settings.model, audio, msg.voice.mime_type
                )
            except Exception:
                logger.exception("failed to transcribe voice note")
                send(
                    settings.telegram_token,
                    msg.chat_id,
                    "🎙️ Sorry, I couldn't transcribe that — please try again.",
                )
                return {"statusCode": 200}
            if not transcript:
                send(
                    settings.telegram_token,
                    msg.chat_id,
                    "🎙️ I couldn't make out any words in that voice note.",
                )
                return {"statusCode": 200}
            send(settings.telegram_token, msg.chat_id, f"🎙️ heard: {transcript}")
            text = transcript
        else:
            if msg.text.strip() in ("/reset", "/clear"):
                store.clear_history(msg.user_id)
                send(
                    settings.telegram_token,
                    msg.chat_id,
                    "🧹 Conversation history cleared.",
                )
                return {"statusCode": 200}
            text = msg.text

        # History handling is best-effort: a corrupt/unreadable blob or a
        # transient load error must never break messaging, so fall back to [].
        history = []
        if settings.history_exchanges:
            try:
                history = store.get_history(msg.user_id)
            except Exception:
                logger.exception("failed to load history; continuing without it")

        deps = AgentDeps(store=store, user_id=msg.user_id, now=now(), new_id=new_id)
        reply, messages = run_message(agent, deps, text, message_history=history)
        send(settings.telegram_token, msg.chat_id, reply)

        # A save failure is logged but does not change the user-visible reply,
        # which has already been sent above.
        if settings.history_exchanges:
            try:
                store.save_history(
                    msg.user_id, trim_history(messages, settings.history_exchanges)
                )
            except Exception:
                logger.exception("failed to save history")
    except Exception as exc:
        logger.exception("error handling update")
        if msg is not None:
            try:
                send(
                    settings.telegram_token,
                    msg.chat_id,
                    f"⚠️ Something went wrong: {exc}",
                )
            except Exception:
                logger.exception("failed to send error reply")
    return {"statusCode": 200}


def _report_init_failure(event, exc: Exception) -> None:
    """Best-effort reply to the chat when initialization fails before handle().

    Setup errors (bad config, unknown LLM provider) happen before the agent
    exists, so the normal in-handler error path never runs and the user sees
    nothing. Reach for the token and chat id directly to surface the error.
    """
    try:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        body = event.get("body")
        update = json.loads(body) if isinstance(body, str) else (body or {})
        msg = parse_update(update)
        if token and msg is not None:
            send_message(token, msg.chat_id, f"⚠️ Bot misconfigured: {exc}")
    except Exception:
        logger.exception("failed to report init failure")


def lambda_handler(event, context) -> dict:
    try:
        settings = load_settings(os.environ)
        store = Store(settings.table_name)
        agent = build_agent(settings.model)
        # Build the transcriber Agent once so it is reused across warm Lambda
        # invocations, mirroring how the chat agent is cached.
        transcriber = partial(transcribe, agent=build_transcriber(settings.model))
    except Exception as exc:
        logger.exception("error during initialization")
        _report_init_failure(event, exc)
        return {"statusCode": 200}
    return handle(event, settings, store, agent, transcriber=transcriber)
