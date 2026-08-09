# ------------------------------------------------------------------------------
# PDF manuals source of record (S3 → ingest → on-box Chroma). Not SageMaker.
# ------------------------------------------------------------------------------

variable "enable_manuals_bucket" {
  description = "Create S3 bucket for OEM PDF manuals"
  type        = bool
  default     = true
}

variable "manuals_bucket_name" {
  description = "Globally unique S3 bucket name for manuals (empty = auto name)"
  type        = string
  default     = ""
}

resource "aws_s3_bucket" "manuals" {
  count  = var.enable_manuals_bucket ? 1 : 0
  bucket = var.manuals_bucket_name != "" ? var.manuals_bucket_name : "${local.short_name}-manuals-${data.aws_caller_identity.current.account_id}"

  tags = merge(local.common_tags, { Purpose = "oem-manuals" })
}

resource "aws_s3_bucket_public_access_block" "manuals" {
  count  = var.enable_manuals_bucket ? 1 : 0
  bucket = aws_s3_bucket.manuals[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "manuals" {
  count  = var.enable_manuals_bucket ? 1 : 0
  bucket = aws_s3_bucket.manuals[0].id

  versioning_configuration {
    status = "Enabled"
  }
}
