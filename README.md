# Telegram Memory Bot

### What?

This repo is a Telegram bot for capturing and recalling notes (you send, it stores and answers — it never pushes anything at you): send it unstructured notes or voice messages and it auto-files them into categories;
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

### Why?

I have the memory of a goldfish, and for convenience use telegram saved messages often. However, as anyone who uses them knows its unstructured and does not have categories.

I used Notion/Trello for a while but it got exhausting to manually categorize stuff. I just wanted something to do it for me. A PA of sorts but with minimal configuration and upkeep and most importantly, cost.

## How to use?

### Deployment

You just need to create a new bot on telegram via BotFather, then one click apply (if you already have the prereqs).

Prerequisites: AWS CLI configured, Docker running, Terraform >= 1.5.

One `terraform apply` provisions everything on AWS (ECR image, Lambda,
DynamoDB, API Gateway, billing alarm) and registers the Telegram webhook.

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
# edit: telegram_bot_token, anthropic_api_key, allowed_users
cd infra && terraform init && terraform apply
```

See `infra/NOTES.md` for details and optional settings.

### Methods of use

Right now unstructured text and voice modes are supported.

For voice notes (or audio file) and the bot transcribes it with the
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

## Required Environment variables

| Var                            | Default                       | Purpose                                                                                  |
| ------------------------------ | ----------------------------- | ---------------------------------------------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN`           | —                             | Bot token from @BotFather                                                                |
| `ANTHROPIC_API_KEY`            | —                             | Model provider key                                                                       |
| `MEMORY_BOT_MODEL`             | `anthropic:claude-sonnet-4-6` | `provider:model` string                                                                  |
| `MEMORY_BOT_TABLE`             | `notes`                       | DynamoDB table name                                                                      |
| `MEMORY_BOT_ALLOWED_USERS`     | (empty)                       | Comma-separated Telegram user IDs allowed (required — the bot ignores everyone if empty) |
| `MEMORY_BOT_WEBHOOK_SECRET`    | (empty)                       | Telegram webhook secret token; verified on each request                                  |
| `MEMORY_BOT_HISTORY_EXCHANGES` | `10`                          | Recent user↔bot exchanges remembered; `0` disables conversation memory                   |
| `MEMORY_BOT_VOICE_MAX_SECONDS` | `120`                         | Longest voice note transcribed, in seconds; longer notes are rejected                    |
| `GOOGLE_API_KEY`               | —                             | Gemini key used for voice-note transcription                                             |

Set these env vars in
`terraform.tfvars` and you're good to go!

## Design choices

**Memory is deliberately dumb.** Rather than a vector DB, embeddings, or a
semantic-search layer, every live (non-done) note is injected straight into the
model's context each turn. At personal scale — a handful to a few hundred notes
— a long-context model reasons over the whole set directly, so there's no
retrieval layer, no index to keep in sync, and no similarity search to tune or
pay for. Most "second brain" tools reach for embeddings on day one; here that
whole machine is skipped on purpose, which is the main reason the stack stays
this simple and this cheap. The tradeoff is that this only holds while your note
volume is small; it is not built to scale to tens of thousands of notes.

**Serverless, minimal cost.** The stack is deliberately serverless (Lambda +
DynamoDB + API Gateway) rather than a long-running server. For a personal bot
handling a few messages a day, this sits almost entirely within AWS free tiers
— running cost is effectively zero.

| Resource                   | Cost             | Notes                                                                                                                                                                                                                                                                                                                   |
| -------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Lambda (bot, 512 MB, 30s)  | ~$0              | Free tier: 1M requests + 400k GB-s/month, perpetual. A few msgs/day is nothing.                                                                                                                                                                                                                                         |
| API Gateway (HTTP API)     | ~$0 then $1.00/M | First 1M requests/month free for 12 months, then $1.00/million. Personal volume → cents at most.                                                                                                                                                                                                                        |
| DynamoDB (PAY_PER_REQUEST) | ~$0              | On-demand: 25 GB storage free, then writes/reads per-request. Items are tiny — effectively free at this scale.                                                                                                                                                                                                          |
| CloudWatch Logs (Lambda)   | ~$0              | 7-day retention set, so logs don't accumulate. Ingestion 5 GB/mo free.                                                                                                                                                                                                                                                  |
| SNS (alarm topic + email)  | ~$0              | Only created if `alarm_email` set. Email notifications are free.                                                                                                                                                                                                                                                        |
| CloudWatch billing alarm   | ~$0              | First 10 alarms free; 1 alarm here.                                                                                                                                                                                                                                                                                     |
| ECR (image repo)           | ~$0              | 500 MB free, then $0.10/GB-mo. A Lambda container image is ~200 MB–1 GB. A lifecycle policy keeps only the most recent image (`imageCountMoreThan: 1` → expire), so each `terraform apply` expires the previous image — storage stays capped at one image and doesn't grow. Right now the image is < 500mb so its free. |

Both CloudWatch logs (7-day retention) and ECR (lifecycle policy keeps only the
latest image) are bounded, so nothing grows unbounded — the stack stays
effectively free at this scale.
