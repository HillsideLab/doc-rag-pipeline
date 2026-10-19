# The state machine (definition in statemachine.asl.json) and its role.
# No CloudWatch Logs for Step Functions: that needs logs:CreateLogDelivery and similar on "*".
# The execution history (aws stepfunctions get-execution-history) shows every step.

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${local.prefix}-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

resource "aws_iam_role_policy" "sfn" {
  name = "${local.prefix}-sfn"
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [for f in aws_lambda_function.step : f.arn]
      },
      {
        # MarkIndexed and MarkFailed write to DynamoDB directly, without a Lambda.
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.documents.arn]
      },
    ]
  })
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${local.prefix}-pipeline"
  type     = "STANDARD"
  role_arn = aws_iam_role.sfn.arn

  definition = templatefile("${path.module}/statemachine.asl.json", {
    register_arn         = aws_lambda_function.step["register"].arn
    start_extraction_arn = aws_lambda_function.step["start-extraction"].arn
    check_extraction_arn = aws_lambda_function.step["check-extraction"].arn
    save_extraction_arn  = aws_lambda_function.step["save-extraction"].arn
    index_document_arn   = aws_lambda_function.step["index-document"].arn
    table_name           = aws_dynamodb_table.documents.name
  })

  depends_on = [aws_iam_role_policy.sfn]
}
