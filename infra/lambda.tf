# Five Lambda functions from one zip (scripts/build_lambda.sh); only the handler differs.
# Each function has its own role with only the permissions its step needs.

locals {
  lambda_zip = "${path.module}/../build/lambda.zip"

  # Memory in MB, timeout in seconds. Nothing runs below 256 MB: at 128 MB, start-extraction
  # and check-extraction used 104 MB (mostly boto3), too close to the limit.
  functions = {
    register         = { handler = "register", memory = 256, timeout = 60 }
    start-extraction = { handler = "start_extraction", memory = 256, timeout = 30 }
    check-extraction = { handler = "check_extraction", memory = 256, timeout = 30 }
    save-extraction  = { handler = "save_extraction", memory = 1024, timeout = 180 }
    index-document   = { handler = "index", memory = 1024, timeout = 300 }
  }

  # Statements per function, on top of writing its own logs.
  function_statements = {
    register = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${local.bucket_arn}/incoming/*", "${local.bucket_arn}/textract-cache/*"]
      },
      {
        # Without ListBucket, HeadObject on a missing cache key returns 403 instead of 404,
        # and the code treats 403 as an error (so a permission problem never costs money).
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [local.bucket_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.documents.arn]
      },
    ]
    start-extraction = [
      {
        # Textract has no resource-level permissions, so "*" is the only option.
        Effect   = "Allow"
        Action   = ["textract:StartDocumentAnalysis"]
        Resource = ["*"]
      },
      {
        # Textract reads the PDF with the caller's permissions.
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${local.bucket_arn}/incoming/*"]
      },
    ]
    check-extraction = [
      {
        Effect   = "Allow"
        Action   = ["textract:GetDocumentAnalysis"]
        Resource = ["*"]
      },
    ]
    save-extraction = [
      {
        Effect   = "Allow"
        Action   = ["textract:GetDocumentAnalysis"]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["${local.bucket_arn}/textract-cache/*"]
      },
    ]
    index-document = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${local.bucket_arn}/textract-cache/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.pinecone_api_key.arn]
      },
    ]
  }

  # The same settings for every function; none of them is secret (the key is in Secrets Manager).
  lambda_environment = {
    S3_BUCKET            = var.bucket_name
    TABLE_NAME           = aws_dynamodb_table.documents.name
    PINECONE_INDEX       = var.pinecone_index
    PINECONE_NAMESPACE   = var.pinecone_namespace
    PINECONE_EMBED_MODEL = var.pinecone_embed_model
    PINECONE_SECRET_ARN  = aws_secretsmanager_secret.pinecone_api_key.arn
    FORCE_FAIL_STEP      = var.force_fail_step
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
  for_each           = local.functions
  name               = "${local.prefix}-lambda-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.prefix}-${each.key}"
  retention_in_days = 7
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions
  name     = "${local.prefix}-lambda-${each.key}"
  role     = aws_iam_role.lambda[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          # The log group is created above, so the function only writes streams and events.
          Effect   = "Allow"
          Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
          Resource = ["${aws_cloudwatch_log_group.lambda[each.key].arn}:*"]
        },
      ],
      local.function_statements[each.key],
    )
  })
}

resource "aws_lambda_function" "step" {
  for_each         = local.functions
  function_name    = "${local.prefix}-${each.key}"
  role             = aws_iam_role.lambda[each.key].arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "src.pipeline.handlers.${each.value.handler}"
  filename         = local.lambda_zip
  source_code_hash = filebase64sha256(local.lambda_zip)
  memory_size      = each.value.memory
  timeout          = each.value.timeout

  environment {
    variables = local.lambda_environment
  }

  # JSON for the runtime's own lines too (uncaught errors, START / END / REPORT), so every line
  # in the log group is JSON. The handlers' lines keep their own format (logging_json.py).
  logging_config {
    log_format = "JSON"
  }

  # The log group (7-day retention) and the permissions must exist before the first run.
  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy.lambda]
}
