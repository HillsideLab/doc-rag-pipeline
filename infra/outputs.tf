output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}

output "table_name" {
  value = aws_dynamodb_table.documents.name
}

output "pinecone_secret_arn" {
  description = "Put the Pinecone API key into this secret by hand (README)."
  value       = aws_secretsmanager_secret.pinecone_api_key.arn
}

output "event_rule_name" {
  value = aws_cloudwatch_event_rule.incoming.name
}
