output "invoke_url" {
  description = "Base HTTP API invoke URL."
  value       = aws_apigatewayv2_api.http.api_endpoint
}

output "webhook_url" {
  description = "Full Telegram webhook URL registered with setWebhook."
  value       = "${aws_apigatewayv2_api.http.api_endpoint}/webhook"
}

output "ecr_repository_url" {
  description = "ECR repository holding the Lambda image."
  value       = aws_ecr_repository.bot.repository_url
}

output "table_name" {
  description = "DynamoDB table name."
  value       = aws_dynamodb_table.notes.name
}
