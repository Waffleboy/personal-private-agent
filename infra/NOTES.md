# Deployment

One `terraform apply` provisions everything and registers the Telegram webhook.

## Prerequisites

- AWS CLI configured (`aws configure`) with credentials and a default region.
- Docker installed and running.
- Terraform >= 1.5 installed.

## Steps

1. Copy the example vars and fill in your secrets:

   ```bash
   cp infra/terraform.tfvars.example infra/terraform.tfvars
   # edit infra/terraform.tfvars: telegram_bot_token, llm_api_key, allowed_users
   ```

2. Deploy:

   ```bash
   cd infra
   terraform init
   terraform apply
   ```

That's it — the bot is live. Terraform builds the Lambda container image,
pushes it to ECR, creates the table/Lambda/API Gateway, and registers the
webhook with Telegram.

> **Required:** `allowed_users` must be set to your Telegram numeric user
> ID(s) (comma-separated). If left empty the bot silently ignores every
> message, since the handler rejects any user not in the allow-set.

## Optional

- `alarm_email` — set it to receive billing-alarm emails (you must confirm the
  SNS subscription email).
- `billing_alarm_threshold_usd` — defaults to 5.
- `history_exchanges` — how many recent user↔bot exchanges the bot remembers
  (default 10). Set to `0` to disable conversation memory.
- `voice_max_seconds` — longest voice note the bot will transcribe, in seconds
  (default 120). Longer notes are rejected before download.
- `model`, `table_name` — override defaults if needed.

## Updating the bot

Change code under `src/memory_bot/` and re-run `terraform apply`. The image
hash changes, so Terraform rebuilds, pushes, and updates the Lambda.

## Phase 2 (not built yet)

Reminders/proactive push: add a `schedule_reminder` tool that writes a
due-time row, plus an EventBridge-scheduled Lambda that scans for due rows
and pushes via `sendMessage`. The webhook skeleton is unchanged.
