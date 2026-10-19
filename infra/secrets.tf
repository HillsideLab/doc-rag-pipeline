# Only the container. The value is put in by hand with the AWS CLI, so the key is never in
# tfvars, the Terraform state, or git. No recovery window, so destroy and re-create work.
resource "aws_secretsmanager_secret" "pinecone_api_key" {
  name                    = "${local.prefix}/pinecone-api-key"
  description             = "Pinecone API key for the index Lambda. Value set by hand, not by Terraform."
  recovery_window_in_days = 0
}
