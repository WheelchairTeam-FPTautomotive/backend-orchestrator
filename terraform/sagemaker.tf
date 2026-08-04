# ------------------------------------------------------------------------------
# SageMaker Model Hosting
# ------------------------------------------------------------------------------
# Provisions a private S3 bucket for model artifacts, an IAM execution role for
# SageMaker, a security group for the endpoint, an S3 VPC gateway endpoint to
# keep model downloads off the NAT gateway, and (optionally) the SageMaker
# model, endpoint configuration, and endpoint itself.
# ------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  # Drop the HF author prefix (e.g. "TheBloke/") and remove any non-alphanumeric
  # characters so that generated names stay under AWS 63-character limits.
  sagemaker_model_slug = lower(
    join(
      "-",
      regexall(
        "[a-zA-Z0-9]+",
        element(split("/", var.sagemaker_model_id), length(split("/", var.sagemaker_model_id)) - 1)
      )
    )
  )

  sagemaker_model_name           = "${local.short_name}-llm-model-${local.sagemaker_model_slug}"
  sagemaker_endpoint_config_name = "${local.short_name}-llm-cfg-${local.sagemaker_model_slug}"
  sagemaker_endpoint_name        = "${local.short_name}-llm-ep-${local.sagemaker_model_slug}"

  sagemaker_execution_role_arn = var.sagemaker_execution_role_arn != "" ? var.sagemaker_execution_role_arn : one(aws_iam_role.sagemaker_execution[*].arn)
}

# ------------------------------------------------------------------------------
# S3 Model Artifact Bucket
# ------------------------------------------------------------------------------
resource "aws_s3_bucket" "model_artifacts" {
  bucket = var.sagemaker_model_bucket_name
  tags   = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "model_artifacts" {
  bucket = aws_s3_bucket.model_artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "model_artifacts" {
  bucket = aws_s3_bucket.model_artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowSageMakerRoleRead"
        Effect = "Allow"
        Principal = {
          AWS = local.sagemaker_execution_role_arn
        }
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.model_artifacts.arn,
          "${aws_s3_bucket.model_artifacts.arn}/*"
        ]
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# SageMaker Execution Role
# ------------------------------------------------------------------------------
resource "aws_iam_role" "sagemaker_execution" {
  count = var.sagemaker_execution_role_arn == "" ? 1 : 0

  name = "${local.short_name}-sagemaker-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "sagemaker.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "sagemaker_execution" {
  count = var.sagemaker_execution_role_arn == "" ? 1 : 0

  name = "${local.short_name}-sagemaker-execution-policy"
  role = aws_iam_role.sagemaker_execution[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3ModelArtifacts"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.model_artifacts.arn,
          "${aws_s3_bucket.model_artifacts.arn}/*"
        ]
      },
      {
        Sid    = "ECRPullDLC"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "arn:aws:ecr:${var.aws_region}:763104351884:repository/huggingface-vllm"
      },
      {
        Sid    = "ECRAuthToken"
        Effect = "Allow"
        Action = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/sagemaker/Endpoints/*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Endpoint Networking
# ------------------------------------------------------------------------------
resource "aws_security_group" "sagemaker_endpoint" {
  name_prefix = "${local.short_name}-sagemaker-ep-"
  description = "SageMaker endpoint instance network access"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
    description = "Allow SageMaker service communication within the VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow outbound traffic for S3, ECR, and CloudWatch"
  }

  tags = merge(local.common_tags, { Name = "${local.short_name}-sagemaker-endpoint" })
}

resource "aws_security_group" "sagemaker_runtime_vpc_endpoint" {
  name_prefix = "${local.short_name}-sagemaker-runtime-vpce-"
  description = "SageMaker Runtime VPC Endpoint - ingress from ECS tasks only"
  vpc_id      = module.vpc.vpc_id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
    description     = "HTTPS from ECS tasks only"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.short_name}-sagemaker-runtime-vpce" })
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = module.vpc.private_route_table_ids

  tags = local.common_tags
}

resource "aws_vpc_endpoint" "sagemaker_runtime" {
  vpc_id              = module.vpc.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.sagemaker.runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = module.vpc.private_subnets
  security_group_ids  = [aws_security_group.sagemaker_runtime_vpc_endpoint.id]
  private_dns_enabled = true

  tags = merge(local.common_tags, { Name = "${local.short_name}-sagemaker-runtime-vpce" })
}

# ------------------------------------------------------------------------------
# SageMaker Model, Endpoint Configuration, and Endpoint
# ------------------------------------------------------------------------------
resource "aws_sagemaker_model" "llm" {
  count = var.deploy_sagemaker_model ? 1 : 0

  name               = local.sagemaker_model_name
  execution_role_arn = local.sagemaker_execution_role_arn

  primary_container {
    image          = var.sagemaker_container_image
    model_data_url = "s3://${aws_s3_bucket.model_artifacts.bucket}/models/${local.sagemaker_model_slug}/model.tar.gz"

    environment = {
      SM_NUM_GPUS   = "1"
      SM_VLLM_MODEL = "/opt/ml/model"
      HF_MODEL_ID   = var.sagemaker_model_id
    }
  }

  vpc_config {
    security_group_ids = [aws_security_group.sagemaker_endpoint.id]
    subnets            = module.vpc.private_subnets
  }

  tags = local.common_tags
}

resource "aws_sagemaker_endpoint_configuration" "llm" {
  count = var.deploy_sagemaker_model ? 1 : 0

  name = local.sagemaker_endpoint_config_name

  production_variants {
    variant_name           = "primary"
    model_name             = aws_sagemaker_model.llm[0].name
    initial_instance_count = 1
    instance_type          = var.sagemaker_instance_type
    initial_variant_weight = 1

    model_data_download_timeout_in_seconds            = 1200
    container_startup_health_check_timeout_in_seconds = 1200
  }

  tags = local.common_tags
}

resource "aws_sagemaker_endpoint" "llm" {
  count = var.deploy_sagemaker_model ? 1 : 0

  name                 = local.sagemaker_endpoint_name
  endpoint_config_name = aws_sagemaker_endpoint_configuration.llm[0].name

  tags = local.common_tags
}
