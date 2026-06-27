import json
import boto3
import pytest
from moto import mock_aws

import pydantic_ai.models
from pydantic_ai.models.function import FunctionModel, AgentInfo
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart

from memory_bot.config import Settings
from memory_bot.store import Store
from memory_bot.agent import build_agent
from memory_bot.handler import handle

pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


def _event(user_id, text, headers=None):
    body = {"update_id": 1, "message": {
        "from": {"id": user_id}, "chat": {"id": user_id}, "text": text}}
    event = {"body": json.dumps(body)}
    if headers is not None:
        event["headers"] = headers
    return event


@pytest.fixture
def ctx():
    with mock_aws():
        res = boto3.resource("dynamodb", region_name="us-east-1")
        Store.create_table(res, "notes")
        store = Store("notes", dynamodb_resource=res)
        settings = Settings(table_name="notes",
                            model="anthropic:claude-sonnet-4-6",
                            allowed_users={111}, telegram_token="TOK",
                            telegram_secret="")
        yield settings, store


def _save_agent():
    def call(messages, info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart(
                "save_note", {"text": "x", "category": "idea"})])
        return ModelResponse(parts=[TextPart("Filed under idea.")])
    agent = build_agent("anthropic:claude-sonnet-4-6")
    return agent, FunctionModel(call)


def test_authorized_message_replies_and_saves(ctx):
    settings, store = ctx
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(_event(111, "remember x"), settings, store, agent,
                      send=lambda tok, chat, text: sent.append((chat, text)),
                      now=lambda: "2026-06-27T00:00:00Z", new_id=lambda: "id1")
    assert resp == {"statusCode": 200}
    assert sent and sent[0][0] == 111
    assert len(store.query_notes(111)) == 1


def test_unauthorized_user_ignored(ctx):
    settings, store = ctx
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(_event(999, "remember x"), settings, store, agent,
                      send=lambda tok, chat, text: sent.append((chat, text)),
                      now=lambda: "2026-06-27T00:00:00Z", new_id=lambda: "id1")
    assert resp == {"statusCode": 200}
    assert sent == []
    assert store.query_notes(999) == []


def test_internal_error_still_returns_200(ctx):
    settings, store = ctx
    sent = []

    def boom(messages, info: AgentInfo) -> ModelResponse:
        raise RuntimeError("model exploded")

    agent = build_agent("anthropic:claude-sonnet-4-6")
    with agent.override(model=FunctionModel(boom)):
        resp = handle(_event(111, "hi"), settings, store, agent,
                      send=lambda tok, chat, text: sent.append((chat, text)),
                      now=lambda: "2026-06-27T00:00:00Z", new_id=lambda: "id1")
    assert resp == {"statusCode": 200}
    assert sent and "try again" in sent[0][1].lower()


def test_malformed_body_still_returns_200(ctx):
    settings, store = ctx
    sent = []
    agent = build_agent("anthropic:claude-sonnet-4-6")
    resp = handle({"body": "not-json{{{"}, settings, store, agent,
                  send=lambda tok, chat, text: sent.append((chat, text)),
                  now=lambda: "2026-06-27T00:00:00Z", new_id=lambda: "id1")
    assert resp == {"statusCode": 200}
    assert sent == []


def test_webhook_secret_verification_missing_header(ctx):
    """When secret is configured and header is missing, request is rejected silently."""
    settings, store = ctx
    # Create new settings with a secret configured
    settings = Settings(table_name="notes",
                        model="anthropic:claude-sonnet-4-6",
                        allowed_users={111}, telegram_token="TOK",
                        telegram_secret="my-secret")
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        # Event without headers
        resp = handle(_event(111, "remember x"), settings, store, agent,
                      send=lambda tok, chat, text: sent.append((chat, text)),
                      now=lambda: "2026-06-27T00:00:00Z", new_id=lambda: "id1")
    assert resp == {"statusCode": 200}
    assert sent == []  # Nothing sent, nothing processed
    assert store.query_notes(111) == []  # Nothing saved


def test_webhook_secret_verification_wrong_secret(ctx):
    """When secret is configured and header value is wrong, request is rejected silently."""
    settings, store = ctx
    settings = Settings(table_name="notes",
                        model="anthropic:claude-sonnet-4-6",
                        allowed_users={111}, telegram_token="TOK",
                        telegram_secret="my-secret")
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        # Event with wrong secret
        resp = handle(_event(111, "remember x",
                            headers={"x-telegram-bot-api-secret-token": "wrong-secret"}),
                      settings, store, agent,
                      send=lambda tok, chat, text: sent.append((chat, text)),
                      now=lambda: "2026-06-27T00:00:00Z", new_id=lambda: "id1")
    assert resp == {"statusCode": 200}
    assert sent == []  # Nothing sent, nothing processed
    assert store.query_notes(111) == []  # Nothing saved


def test_webhook_secret_verification_correct_secret(ctx):
    """When secret is configured and header value matches, request is processed normally."""
    settings, store = ctx
    settings = Settings(table_name="notes",
                        model="anthropic:claude-sonnet-4-6",
                        allowed_users={111}, telegram_token="TOK",
                        telegram_secret="my-secret")
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        # Event with correct secret
        resp = handle(_event(111, "remember x",
                            headers={"x-telegram-bot-api-secret-token": "my-secret"}),
                      settings, store, agent,
                      send=lambda tok, chat, text: sent.append((chat, text)),
                      now=lambda: "2026-06-27T00:00:00Z", new_id=lambda: "id1")
    assert resp == {"statusCode": 200}
    assert sent and sent[0][0] == 111  # Message sent
    assert len(store.query_notes(111)) == 1  # Note saved


def test_webhook_secret_not_configured_accepts_requests(ctx):
    """When secret is not configured (empty string), requests are processed regardless of headers."""
    settings, store = ctx
    # settings already has telegram_secret=""
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(_event(111, "remember x",
                            headers={"x-telegram-bot-api-secret-token": "any-value"}),
                      settings, store, agent,
                      send=lambda tok, chat, text: sent.append((chat, text)),
                      now=lambda: "2026-06-27T00:00:00Z", new_id=lambda: "id1")
    assert resp == {"statusCode": 200}
    assert sent and sent[0][0] == 111  # Message sent, processed normally
    assert len(store.query_notes(111)) == 1  # Note saved
