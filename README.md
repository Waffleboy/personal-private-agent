# Telegram Memory Bot

Pull-only Telegram bot: send it notes, it auto-files them into categories;
ask it questions, it answers from your notes. Serverless on AWS Lambda +
DynamoDB, powered by Pydantic AI (model swappable via env var).

## Local dev

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
```

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `TELEGRAM_BOT_TOKEN` | — | Bot token from @BotFather |
| `ANTHROPIC_API_KEY` | — | Model provider key |
| `MEMORY_BOT_MODEL` | `anthropic:claude-sonnet-4-6` | `provider:model` string |
| `MEMORY_BOT_TABLE` | `notes` | DynamoDB table name |
| `MEMORY_BOT_ALLOWED_USERS` | (empty) | Comma-separated Telegram user IDs allowed |

## Deploy (outline)

See `infra/NOTES.md`.
