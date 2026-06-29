variable "aws_region" {
  type        = string
  description = "AWS region to deploy into."
}

variable "telegram_bot_token" {
  type        = string
  description = "Telegram bot token from @BotFather."
  sensitive   = true
}

variable "llm_api_key" {
  type        = string
  description = "API key for the LLM provider selected by `model` (Anthropic, OpenAI, or Gemini)."
  sensitive   = true
}

variable "telegram_webhook_secret" {
  type        = string
  description = "Webhook secret token; a random one is generated if left blank."
  default     = ""
  sensitive   = true
}

variable "model" {
  type        = string
  description = "provider:model string for Pydantic AI."
  default     = "anthropic:claude-sonnet-4-6"
}

variable "allowed_users" {
  type        = string
  description = "Comma-separated Telegram user IDs allowed to use the bot."
  default     = ""
}

variable "table_name" {
  type        = string
  description = "DynamoDB table name."
  default     = "notes"
}

variable "name_prefix" {
  type        = string
  description = "Prefix applied to created resource names."
  default     = "memory-bot"
}

variable "billing_alarm_threshold_usd" {
  type        = number
  description = "USD threshold for the CloudWatch estimated-charges alarm."
  default     = 5
}

variable "history_exchanges" {
  type        = number
  description = "Number of recent user<->bot exchanges the bot remembers. 0 disables history."
  default     = 10
}

variable "alarm_email" {
  type        = string
  description = "If set, an SNS email subscription is created for the billing alarm."
  default     = ""
}
