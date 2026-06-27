from __future__ import annotations

import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Callable

from memory_bot.agent import AgentDeps, build_agent, run_message
from memory_bot.config import load_settings
from memory_bot.store import Store
from memory_bot.telegram import parse_update, send_message

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def handle(event, settings, store, agent, *, send=send_message,
           now: Callable[[], str] = _utcnow,
           new_id: Callable[[], str] = lambda: uuid.uuid4().hex[:12]) -> dict:
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
        deps = AgentDeps(store=store, user_id=msg.user_id, now=now(), new_id=new_id)
        reply = run_message(agent, deps, msg.text)
        send(settings.telegram_token, msg.chat_id, reply)
    except Exception:
        logger.exception("error handling update")
        if msg is not None:
            try:
                send(settings.telegram_token, msg.chat_id,
                     "⚠️ Something went wrong, please try again.")
            except Exception:
                logger.exception("failed to send error reply")
    return {"statusCode": 200}


def lambda_handler(event, context) -> dict:
    settings = load_settings(os.environ)
    store = Store(settings.table_name)
    agent = build_agent(settings.model)
    return handle(event, settings, store, agent)
