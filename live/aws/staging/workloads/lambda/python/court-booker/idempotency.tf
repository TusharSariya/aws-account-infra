resource "aws_dynamodb_table" "idempotency" {
  # checkov:skip=CKV_AWS_119:AWS-owned encryption is adequate for non-secret booking coordination data.
  # checkov:skip=CKV_AWS_28:TTL and application states are sufficient; this is not the booking system of record.
  name         = "court-booker-api-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  ttl {
    attribute_name = "expiration"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false
  }
}
