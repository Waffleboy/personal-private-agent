# Deployment

## 1. DynamoDB table

Create a table `notes` with:
- Partition key `pk` (String), sort key `sk` (String)
- Billing mode: on-demand (PAY_PER_REQUEST)

## 2. Package the Lambda

Pydantic AI + Pydantic add import weight; use a zip with deps or a container
image. Example zip build:

```bash
pip install -r requirements.txt -t build/
cp -r src/memory_bot build/
cd build && zip -r ../function.zip . && cd ..
```

- Runtime: Python 3.12
- Handler: `memory_bot.handler.lambda_handler`
- Env vars: set all from the table in README.
- Timeout: 30s (model calls). Memory: 512MB.
- IAM: allow `dynamodb:PutItem`, `dynamodb:Query` on the table.

## 3. API Gateway

- Create an HTTP API with a single `POST /webhook` route → Lambda integration.
- Note the invoke URL.

## 4. Register the webhook with Telegram

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://<api-id>.execute-api.<region>.amazonaws.com/webhook"}'
```

## 5. Cost guard

Add a CloudWatch billing alarm so a runaway loop can't surprise you.

## Phase 2 (not built yet)

Reminders/proactive push: add a `schedule_reminder` tool that writes a
due-time row, plus an EventBridge-scheduled Lambda that scans for due rows
and pushes via `sendMessage`. The webhook skeleton is unchanged.
