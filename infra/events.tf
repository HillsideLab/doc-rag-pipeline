# S3 -> EventBridge -> Step Functions.
#
# aws_s3_bucket_notification replaces the bucket's whole notification configuration.
# It was checked to be empty before the first apply (README); destroy empties it again.
resource "aws_s3_bucket_notification" "eventbridge" {
  bucket      = var.bucket_name
  eventbridge = true
}

# Only new objects under incoming/ in this bucket start the pipeline. The pipeline itself
# writes only to textract-cache/, and no Lambda role may write to incoming/, so a run can
# never start another run.
resource "aws_cloudwatch_event_rule" "incoming" {
  name        = "${local.prefix}-incoming"
  description = "PDF uploaded to s3://${var.bucket_name}/incoming/"
  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [var.bucket_name] }
      object = { key = [{ prefix = "incoming/" }] }
    }
  })
}

data "aws_iam_policy_document" "events_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events" {
  name               = "${local.prefix}-events"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
}

resource "aws_iam_role_policy" "events" {
  name = "${local.prefix}-events"
  role = aws_iam_role.events.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["states:StartExecution"]
        Resource = [aws_sfn_state_machine.pipeline.arn]
      },
    ]
  })
}

resource "aws_cloudwatch_event_target" "pipeline" {
  rule     = aws_cloudwatch_event_rule.incoming.name
  arn      = aws_sfn_state_machine.pipeline.arn
  role_arn = aws_iam_role.events.arn

  # The execution gets only the bucket and the key, not the whole event.
  input_transformer {
    input_paths = {
      bucket = "$.detail.bucket.name"
      key    = "$.detail.object.key"
    }
    input_template = "{\"bucket\": <bucket>, \"key\": <key>}"
  }
}
