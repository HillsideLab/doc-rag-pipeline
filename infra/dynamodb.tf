# One item per document. doc_id (first 16 hex characters of the PDF's sha256) is the only key:
# the pipeline only ever reads or writes one document by its ID.
resource "aws_dynamodb_table" "documents" {
  name         = "${local.prefix}-documents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "doc_id"

  attribute {
    name = "doc_id"
    type = "S"
  }
}
