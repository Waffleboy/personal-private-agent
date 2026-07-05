import json

import boto3
import pydantic_ai.models
import pytest
from moto import mock_aws
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from memory_bot.agent import build_agent
from memory_bot.config import Settings
from memory_bot.handler import handle, lambda_handler
from memory_bot.store import Store

pydantic_ai.models.ALLOW_MODEL_REQUESTS = False


def _event(user_id, text, headers=None):
    body = {
        "update_id": 1,
        "message": {"from": {"id": user_id}, "chat": {"id": user_id}, "text": text},
    }
    event = {"body": json.dumps(body)}
    if headers is not None:
        event["headers"] = headers
    return event


def _voice_event(user_id, file_id="v1", duration=5, mime="audio/ogg"):
    body = {
        "update_id": 1,
        "message": {
            "from": {"id": user_id},
            "chat": {"id": user_id},
            "voice": {"file_id": file_id, "duration": duration, "mime_type": mime},
        },
    }
    return {"body": json.dumps(body)}


@pytest.fixture
def ctx():
    with mock_aws():
        res = boto3.resource("dynamodb", region_name="us-east-1")
        Store.create_table(res, "notes")
        store = Store("notes", dynamodb_resource=res)
        settings = Settings(
            table_name="notes",
            model="anthropic:claude-sonnet-4-6",
            allowed_users={111},
            telegram_token="TOK",
            telegram_secret="",
        )
        yield settings, store


def _save_agent():
    def call(messages, info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[ToolCallPart("save_note", {"text": "x", "category": "idea"})]
            )
        return ModelResponse(parts=[TextPart("Filed under idea.")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    return agent, FunctionModel(call)


def test_voice_note_transcribed_echoed_and_saved(ctx):
    settings, store = ctx
    sent = []
    downloaded = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _voice_event(111),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
            download=lambda tok, fid: downloaded.append(fid) or b"AUDIO",
            transcriber=lambda m, b, mt: "remember to buy milk",
        )
    assert resp == {"statusCode": 200}
    assert downloaded == ["v1"]
    # Echo sent first, then the agent's reply.
    assert "heard" in sent[0][1].lower()
    assert "buy milk" in sent[0][1]
    assert sent[1][1] == "Filed under idea."
    assert len(store.query_notes(111)) == 1


def test_voice_note_over_cap_rejected_without_download(ctx):
    settings, store = ctx
    sent = []
    downloaded = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _voice_event(111, duration=999),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
            download=lambda tok, fid: downloaded.append(fid) or b"AUDIO",
            transcriber=lambda m, b, mt: "should not run",
        )
    assert resp == {"statusCode": 200}
    assert downloaded == []
    assert sent and "too long" in sent[0][1].lower()
    assert store.query_notes(111) == []


def test_over_cap_message_reports_non_minute_cap(ctx):
    """A sub-minute cap must not be reported as '0 min' (regression on // 60)."""
    settings, store = ctx
    settings = Settings(
        table_name="notes",
        model="anthropic:claude-sonnet-4-6",
        allowed_users={111},
        telegram_token="TOK",
        telegram_secret="",
        voice_max_seconds=45,
    )
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        handle(
            _voice_event(111, duration=999),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
            download=lambda tok, fid: b"AUDIO",
            transcriber=lambda m, b, mt: "should not run",
        )
    assert sent and "45 sec" in sent[0][1]
    assert "0 min" not in sent[0][1]


def test_voice_note_empty_transcript_replies_and_skips_agent(ctx):
    settings, store = ctx
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _voice_event(111),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
            download=lambda tok, fid: b"AUDIO",
            transcriber=lambda m, b, mt: "",
        )
    assert resp == {"statusCode": 200}
    assert sent and "make out" in sent[0][1].lower()
    assert store.query_notes(111) == []


def test_voice_note_transcribe_failure_replies_gracefully(ctx):
    settings, store = ctx
    sent = []

    def boom(m, b, mt):
        raise RuntimeError("gemini down")

    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _voice_event(111),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
            download=lambda tok, fid: b"AUDIO",
            transcriber=boom,
        )
    assert resp == {"statusCode": 200}
    assert sent and "🎙️" in sent[0][1]
    assert "went wrong" not in sent[0][1].lower()
    assert store.query_notes(111) == []


def test_reset_command_clears_history_and_skips_agent(ctx):
    settings, store = ctx
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    store.save_history(111, [ModelRequest(parts=[UserPromptPart(content="old")])])
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _event(111, "/reset"),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert store.get_history(111) == []
    assert sent and "cleared" in sent[0][1].lower()
    # Agent did not save a note.
    assert store.query_notes(111) == []


def test_clear_command_alias(ctx):
    settings, store = ctx
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _event(111, "/clear"),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert sent and "cleared" in sent[0][1].lower()


def test_history_persisted_across_two_messages(ctx):
    settings, store = ctx
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        handle(
            _event(111, "remember x"),
            settings, store, agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    # After one exchange, history is persisted (non-empty).
    assert store.get_history(111) != []


def test_two_turn_history_gives_agent_prior_context(ctx):
    """End-to-end proof that history flows between two separate handle() calls:
    the second turn's FunctionModel must see the first turn's user text in the
    message history it receives, proving the load->run->trim->save->reload
    round-trip carries context across messages."""
    settings, store = ctx
    seen_user_prompt_counts = []
    saw_first_message_on_turn2 = []

    def call(messages, info: AgentInfo) -> ModelResponse:
        user_prompts = [
            p
            for m in messages
            for p in getattr(m, "parts", [])
            if getattr(p, "part_kind", None) == "user-prompt"
        ]
        seen_user_prompt_counts.append(len(user_prompts))
        # On the second turn, record whether turn 1's text is visible.
        if len(seen_user_prompt_counts) == 2:
            texts = " ".join(str(p.content) for p in user_prompts)
            saw_first_message_on_turn2.append("first message" in texts)
        return ModelResponse(parts=[TextPart("ok")])

    agent = build_agent("anthropic:claude-sonnet-4-6")
    model = FunctionModel(call)
    sent = []
    with agent.override(model=model):
        handle(
            _event(111, "first message"),
            settings, store, agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
        handle(
            _event(111, "second message"),
            settings, store, agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id2",
        )

    # Turn 2 saw more user prompts than turn 1 (the first turn's prompt persisted).
    assert seen_user_prompt_counts[0] == 1
    assert seen_user_prompt_counts[1] > seen_user_prompt_counts[0]
    # And specifically, turn 1's literal text was present on turn 2.
    assert saw_first_message_on_turn2 == [True]


def test_history_disabled_when_zero(ctx):
    settings, store = ctx
    settings = Settings(
        table_name="notes",
        model="anthropic:claude-sonnet-4-6",
        allowed_users={111},
        telegram_token="TOK",
        telegram_secret="",
        history_exchanges=0,
    )
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        handle(
            _event(111, "remember x"),
            settings, store, agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    # With history disabled, nothing is persisted.
    assert store.get_history(111) == []


def test_authorized_message_replies_and_saves(ctx):
    settings, store = ctx
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _event(111, "remember x"),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert sent and sent[0][0] == 111
    assert len(store.query_notes(111)) == 1


def test_unauthorized_user_ignored(ctx):
    settings, store = ctx
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _event(999, "remember x"),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
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
        resp = handle(
            _event(111, "hi"),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert sent and "went wrong" in sent[0][1].lower()
    # The actual error detail is surfaced so the user can see what broke.
    assert "model exploded" in sent[0][1]


def test_history_load_failure_still_replies(ctx):
    """A failure loading history must not break messaging: the agent still
    runs and the user gets a normal reply (not the 'went wrong' error)."""
    settings, store = ctx
    store.get_history = lambda uid: (_ for _ in ()).throw(RuntimeError("boom"))
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _event(111, "remember x"),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert sent and sent[0][0] == 111
    assert "went wrong" not in sent[0][1].lower()
    assert sent[0][1] == "Filed under idea."


def test_history_save_failure_still_replies(ctx):
    """A failure saving history is logged but does not change the
    user-visible reply: the normal reply is still sent."""
    settings, store = ctx
    store.save_history = lambda uid, msgs: (_ for _ in ()).throw(
        RuntimeError("boom")
    )
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _event(111, "remember x"),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert sent and sent[0][0] == 111
    assert "went wrong" not in sent[0][1].lower()
    assert sent[0][1] == "Filed under idea."


def test_init_failure_reports_error_to_chat(monkeypatch):
    """A crash during init (bad config / unknown provider) is surfaced to the
    user's chat instead of failing silently before handle() runs."""
    sent = []
    monkeypatch.setattr(
        "memory_bot.handler.send_message",
        lambda tok, chat, text: sent.append((chat, text)),
    )
    # An unknown provider makes build_agent() raise during init, mirroring the
    # real "Unknown provider: google-gla" failure.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TOK")
    monkeypatch.setenv("MEMORY_BOT_ALLOWED_USERS", "111")
    monkeypatch.setenv("MEMORY_BOT_MODEL", "bogus-provider:some-model")
    event = _event(111, "hi")
    resp = lambda_handler(event, None)
    assert resp == {"statusCode": 200}
    assert sent and sent[0][0] == 111
    assert "Unknown provider" in sent[0][1]


def test_malformed_body_still_returns_200(ctx):
    settings, store = ctx
    sent = []
    agent = build_agent("anthropic:claude-sonnet-4-6")
    resp = handle(
        {"body": "not-json{{{"},
        settings,
        store,
        agent,
        send=lambda tok, chat, text: sent.append((chat, text)),
        now=lambda: "2026-06-27T00:00:00Z",
        new_id=lambda: "id1",
    )
    assert resp == {"statusCode": 200}
    assert sent == []


def test_webhook_secret_verification_missing_header(ctx):
    """When secret is configured and header is missing, request is rejected silently."""
    settings, store = ctx
    # Create new settings with a secret configured
    settings = Settings(
        table_name="notes",
        model="anthropic:claude-sonnet-4-6",
        allowed_users={111},
        telegram_token="TOK",
        telegram_secret="my-secret",
    )
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        # Event without headers
        resp = handle(
            _event(111, "remember x"),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert sent == []  # Nothing sent, nothing processed
    assert store.query_notes(111) == []  # Nothing saved


def test_webhook_secret_verification_wrong_secret(ctx):
    """When secret is configured and header value is wrong, request is rejected."""
    settings, store = ctx
    settings = Settings(
        table_name="notes",
        model="anthropic:claude-sonnet-4-6",
        allowed_users={111},
        telegram_token="TOK",
        telegram_secret="my-secret",
    )
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        # Event with wrong secret
        resp = handle(
            _event(
                111,
                "remember x",
                headers={"x-telegram-bot-api-secret-token": "wrong-secret"},
            ),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert sent == []  # Nothing sent, nothing processed
    assert store.query_notes(111) == []  # Nothing saved


def test_webhook_secret_verification_correct_secret(ctx):
    """When secret is configured and header value matches, request is processed."""
    settings, store = ctx
    settings = Settings(
        table_name="notes",
        model="anthropic:claude-sonnet-4-6",
        allowed_users={111},
        telegram_token="TOK",
        telegram_secret="my-secret",
    )
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        # Event with correct secret
        resp = handle(
            _event(
                111,
                "remember x",
                headers={"x-telegram-bot-api-secret-token": "my-secret"},
            ),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert sent and sent[0][0] == 111  # Message sent
    assert len(store.query_notes(111)) == 1  # Note saved


def test_webhook_secret_not_configured_accepts_requests(ctx):
    """When secret is not configured (empty), requests are processed regardless."""
    settings, store = ctx
    # settings already has telegram_secret=""
    sent = []
    agent, model = _save_agent()
    with agent.override(model=model):
        resp = handle(
            _event(
                111,
                "remember x",
                headers={"x-telegram-bot-api-secret-token": "any-value"},
            ),
            settings,
            store,
            agent,
            send=lambda tok, chat, text: sent.append((chat, text)),
            now=lambda: "2026-06-27T00:00:00Z",
            new_id=lambda: "id1",
        )
    assert resp == {"statusCode": 200}
    assert sent and sent[0][0] == 111  # Message sent, processed normally
    assert len(store.query_notes(111)) == 1  # Note saved
