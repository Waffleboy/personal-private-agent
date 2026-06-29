from memory_bot.config import load_settings


def test_load_settings_parses_env():
    env = {
        "MEMORY_BOT_TABLE": "notes",
        "MEMORY_BOT_MODEL": "anthropic:claude-sonnet-4-6",
        "MEMORY_BOT_ALLOWED_USERS": "111,222",
        "TELEGRAM_BOT_TOKEN": "tok",
    }
    s = load_settings(env)
    assert s.table_name == "notes"
    assert s.model == "anthropic:claude-sonnet-4-6"
    assert s.allowed_users == {111, 222}
    assert s.telegram_token == "tok"


def test_load_settings_defaults():
    s = load_settings({"TELEGRAM_BOT_TOKEN": "tok"})
    assert s.table_name == "notes"
    assert s.model == "anthropic:claude-sonnet-4-6"
    assert s.allowed_users == set()
    assert s.telegram_secret == ""


def test_history_exchanges_default():
    s = load_settings({"TELEGRAM_BOT_TOKEN": "tok"})
    assert s.history_exchanges == 10


def test_history_exchanges_parsed():
    s = load_settings(
        {"TELEGRAM_BOT_TOKEN": "tok", "MEMORY_BOT_HISTORY_EXCHANGES": "3"}
    )
    assert s.history_exchanges == 3
