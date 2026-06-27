terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

locals {
  registry = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"

  # Hash of everything that affects the image, used as the image tag.
  source_files = sort(setunion(
    fileset("${path.module}/..", "Dockerfile"),
    fileset("${path.module}/..", "requirements.txt"),
    fileset("${path.module}/..", "src/memory_bot/*.py"),
  ))
  source_hash = substr(sha1(join("", [
    for f in local.source_files :
    filesha1("${path.module}/../${f}")
  ])), 0, 12)

  image_uri = "${aws_ecr_repository.bot.repository_url}:${local.source_hash}"
}

resource "aws_ecr_repository" "bot" {
  name                 = var.name_prefix
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "null_resource" "image_push" {
  triggers = {
    source_hash = local.source_hash
    repo_url    = aws_ecr_repository.bot.repository_url
  }

  provisioner "local-exec" {
    working_dir = "${path.module}/.."
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      aws ecr get-login-password --region ${var.aws_region} \
        | docker login --username AWS --password-stdin ${local.registry}
      docker build -t ${local.image_uri} .
      docker push ${local.image_uri}
    EOT
  }
}

resource "aws_dynamodb_table" "notes" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.name_prefix}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "lambda_perms" {
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:*:*:*"]
  }
  statement {
    sid       = "Dynamo"
    actions   = ["dynamodb:PutItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.notes.arn]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.name_prefix}-lambda"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_perms.json
}

resource "random_password" "webhook_secret" {
  length  = 32
  special = false
}

locals {
  webhook_secret = var.telegram_webhook_secret != "" ? var.telegram_webhook_secret : random_password.webhook_secret.result
}

resource "aws_lambda_function" "bot" {
  function_name = var.name_prefix
  role          = aws_iam_role.lambda.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  memory_size   = 512
  timeout       = 30

  depends_on = [null_resource.image_push]

  environment {
    variables = {
      TELEGRAM_BOT_TOKEN        = var.telegram_bot_token
      ANTHROPIC_API_KEY         = var.anthropic_api_key
      MEMORY_BOT_MODEL          = var.model
      MEMORY_BOT_TABLE          = var.table_name
      MEMORY_BOT_ALLOWED_USERS  = var.allowed_users
      MEMORY_BOT_WEBHOOK_SECRET = local.webhook_secret
    }
  }
}

resource "aws_apigatewayv2_api" "http" {
  name          = var.name_prefix
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.bot.arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "webhook" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "POST /webhook"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.bot.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

resource "aws_sns_topic" "alarm" {
  provider = aws.us_east_1
  count    = var.alarm_email != "" ? 1 : 0
  name     = "${var.name_prefix}-alarm"
}

resource "aws_sns_topic_subscription" "alarm_email" {
  provider  = aws.us_east_1
  count     = var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alarm[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "billing" {
  provider            = aws.us_east_1
  alarm_name          = "${var.name_prefix}-billing"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 21600
  statistic           = "Maximum"
  threshold           = var.billing_alarm_threshold_usd
  alarm_description   = "Estimated AWS charges exceeded threshold."
  dimensions          = { Currency = "USD" }
  alarm_actions       = var.alarm_email != "" ? [aws_sns_topic.alarm[0].arn] : []
}

resource "null_resource" "set_webhook" {
  triggers = {
    invoke_url = aws_apigatewayv2_api.http.api_endpoint
    secret     = local.webhook_secret
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      curl -fsS -X POST "https://api.telegram.org/bot${var.telegram_bot_token}/setWebhook" \
        -H "Content-Type: application/json" \
        -d '{"url":"${aws_apigatewayv2_api.http.api_endpoint}/webhook","secret_token":"${local.webhook_secret}"}'
    EOT
  }

  depends_on = [aws_apigatewayv2_route.webhook, aws_lambda_permission.apigw]
}
