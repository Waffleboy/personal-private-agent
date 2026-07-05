# Telegram Memory Bot

Pull-only Telegram bot: send it notes, it auto-files them into categories;
ask it questions, it answers from your notes. Serverless on AWS Lambda +
DynamoDB, powered by Pydantic AI (model swappable via env var).

Notes are filed under broad, durable life-areas (e.g. `work`, `school`,
`family`, `health`, `finance`, `todo`) rather than a restatement of the note
itself, and the model prefers reusing your existing categories over coining
new near-duplicates. So "reply to my students' emails" lands in `school`, not
`student_emails`.

The bot also remembers your recent conversation (the last 10 user↔bot
exchanges by default) so follow-up questions keep context. Send `/reset`
(or `/clear`) to wipe your stored history.

## Voice notes

Send a voice note (or audio file) and the bot transcribes it with the
configured Gemini model, echoes the transcript back as `🎙️ heard: …`, then
processes it exactly like a typed message. Notes longer than
`MEMORY_BOT_VOICE_MAX_SECONDS` (default 120) are rejected before download.
Voice support requires the `google` provider extra (already declared in
`pyproject.toml`) and a `GOOGLE_API_KEY`.

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
| `MEMORY_BOT_ALLOWED_USERS` | (empty) | Comma-separated Telegram user IDs allowed (required — the bot ignores everyone if empty) |
| `MEMORY_BOT_WEBHOOK_SECRET` | (empty) | Telegram webhook secret token; verified on each request |
| `MEMORY_BOT_HISTORY_EXCHANGES` | `10` | Recent user↔bot exchanges remembered; `0` disables conversation memory |
| `MEMORY_BOT_VOICE_MAX_SECONDS` | `120` | Longest voice note transcribed, in seconds; longer notes are rejected |
| `GOOGLE_API_KEY` | — | Gemini key used for voice-note transcription |

When deploying with Terraform (below), these are set for you from
`terraform.tfvars` — you don't set them by hand.

## Deploy

One `terraform apply` provisions everything on AWS (ECR image, Lambda,
DynamoDB, API Gateway, billing alarm) and registers the Telegram webhook.

Prerequisites: AWS CLI configured, Docker running, Terraform >= 1.5.

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
# edit: telegram_bot_token, anthropic_api_key, allowed_users
cd infra && terraform init && terraform apply
```

See `infra/NOTES.md` for details and optional settings.
