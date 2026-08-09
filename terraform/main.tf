provider "aws" {
  region = var.aws_region
}

locals {
  short_name = "${var.project_name}-${var.environment}"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # Legacy network (NAT) only when ECS, AOSS, or SageMaker needs the custom VPC.
  need_legacy_vpc = var.enable_ecs || var.enable_aoss || var.deploy_sagemaker_model
}

# ------------------------------------------------------------------------------
# Container Registry
# ------------------------------------------------------------------------------
resource "aws_ecr_repository" "backend_orchestrator" {
  count                = var.enable_ecs ? 1 : 0
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# Networking
# ------------------------------------------------------------------------------
module "vpc" {
  count   = local.need_legacy_vpc ? 1 : 0
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${local.short_name}-vpc"
  cidr = var.vpc_cidr

  azs             = var.availability_zones
  public_subnets  = var.public_subnet_cidrs
  private_subnets = var.private_subnet_cidrs

  enable_nat_gateway   = var.enable_ecs || var.deploy_sagemaker_model
  single_nat_gateway   = true
  enable_dns_hostnames = true
  enable_dns_support   = true

  public_subnet_tags = {
    Tier = "public"
  }

  private_subnet_tags = {
    Tier = "private"
  }

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# Security Groups
# ------------------------------------------------------------------------------
resource "aws_security_group" "alb" {
  count       = var.enable_ecs ? 1 : 0
  name_prefix = "${local.short_name}-alb-"
  description = "Allow HTTP from the internet to the ALB"
  vpc_id      = module.vpc[0].vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "HTTP from internet"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.short_name}-alb" })
}

resource "aws_security_group" "ecs_tasks" {
  count       = var.enable_ecs ? 1 : 0
  name_prefix = "${local.short_name}-ecs-tasks-"
  description = "Allow traffic from ALB to ECS Fargate tasks"
  vpc_id      = module.vpc[0].vpc_id

  ingress {
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb[0].id]
    description     = "Traffic from ALB"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.short_name}-ecs-tasks" })
}

resource "aws_security_group" "opensearch_endpoint" {
  count       = var.enable_aoss ? 1 : 0
  name_prefix = "${local.short_name}-opensearch-"
  description = "Allow HTTPS from ECS tasks to OpenSearch Serverless VPC endpoint"
  vpc_id      = module.vpc[0].vpc_id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "HTTPS from VPC (AOSS VPC endpoint)"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.short_name}-opensearch-endpoint" })
}

# ------------------------------------------------------------------------------
# Application Load Balancer
# ------------------------------------------------------------------------------
module "alb" {
  count   = var.enable_ecs ? 1 : 0
  source  = "terraform-aws-modules/alb/aws"
  version = "~> 9.0"

  name = "${local.short_name}-alb"

  load_balancer_type = "application"
  vpc_id             = module.vpc[0].vpc_id
  subnets            = module.vpc[0].public_subnets
  security_groups    = [aws_security_group.alb[0].id]

  listeners = {
    http = {
      port     = 80
      protocol = "HTTP"
      forward = {
        target_group_key = "ecs"
      }
    }
  }

  target_groups = {
    ecs = {
      name_prefix          = "ecs-"
      protocol             = "HTTP"
      port                 = var.container_port
      target_type          = "ip"
      deregistration_delay = 30
      create_attachment    = false

      health_check = {
        enabled             = true
        healthy_threshold   = 2
        interval            = 30
        matcher             = "200"
        path                = "/api/v1/health"
        port                = "traffic-port"
        protocol            = "HTTP"
        timeout             = 5
        unhealthy_threshold = 3
      }
    }
  }

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# Logging & Secrets
# ------------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "ecs" {
  count             = var.enable_ecs ? 1 : 0
  name              = "/ecs/${local.short_name}"
  retention_in_days = 7
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "ecs_service" {
  count             = var.enable_ecs ? 1 : 0
  name              = "/ecs/${local.short_name}-service"
  retention_in_days = 7
  tags              = local.common_tags
}

resource "aws_secretsmanager_secret" "openai_api_key" {
  count                   = var.enable_ecs ? 1 : 0
  name                    = "${local.short_name}-openai-api-key"
  description             = "OpenAI API key for the backend orchestrator"
  recovery_window_in_days = 7
  tags                    = local.common_tags
}

resource "aws_secretsmanager_secret_version" "openai_api_key" {
  count         = var.enable_ecs ? 1 : 0
  secret_id     = aws_secretsmanager_secret.openai_api_key[0].id
  secret_string = var.openai_api_key
}

# ------------------------------------------------------------------------------
# ECS Cluster
# ------------------------------------------------------------------------------
module "ecs_cluster" {
  count   = var.enable_ecs ? 1 : 0
  source  = "terraform-aws-modules/ecs/aws"
  version = "~> 5.0"

  cluster_name = "${local.short_name}-cluster"

  fargate_capacity_providers = {
    FARGATE = {
      default_capacity_provider_strategy = {
        weight = 100
      }
    }
  }

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# ECS Service (Fargate)
# ------------------------------------------------------------------------------
module "ecs_service" {
  count   = var.enable_ecs ? 1 : 0
  source  = "terraform-aws-modules/ecs/aws//modules/service"
  version = "~> 5.0"

  name        = "${local.short_name}-service"
  cluster_arn = module.ecs_cluster[0].cluster_arn

  cpu    = var.fargate_cpu
  memory = var.fargate_memory

  desired_count      = var.desired_count
  subnet_ids         = module.vpc[0].private_subnets
  security_group_ids = [aws_security_group.ecs_tasks[0].id]
  assign_public_ip   = false

  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]

  create_task_exec_iam_role = false
  create_tasks_iam_role     = false

  task_exec_iam_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.existing_task_execution_role_name}"
  tasks_iam_role_arn     = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.existing_task_role_name}"

  container_definitions = {
    backend-orchestrator = {
      name      = "backend-orchestrator"
      image     = "${aws_ecr_repository.backend_orchestrator[0].repository_url}:${var.image_tag}"
      essential = true

      readonly_root_filesystem = false

      cpu    = var.fargate_cpu
      memory = var.fargate_memory

      port_mappings = [
        {
          containerPort = var.container_port
          hostPort      = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "UVICORN_HOST", value = "0.0.0.0" },
        { name = "UVICORN_PORT", value = tostring(var.container_port) },
        { name = "LOG_LEVEL", value = var.log_level },
        { name = "CORE_AI_URL", value = var.core_ai_url },
        { name = "APP_NAME", value = "KMS Cockpit API Gateway Orchestrator" },
        { name = "APP_VERSION", value = "1.0.0" },
        { name = "SAGEMAKER_LLM_ENDPOINT_NAME", value = var.deploy_sagemaker_model ? aws_sagemaker_endpoint.llm[0].name : "" },
        { name = "SAGEMAKER_REGION", value = var.aws_region },
        { name = "SAGEMAKER_USE_VPC_ENDPOINT", value = "true" },
        { name = "SAGEMAKER_VPC_ENDPOINT_URL", value = "https://${aws_vpc_endpoint.sagemaker_runtime[0].dns_entry[0].dns_name}" },
        { name = "SAGEMAKER_MODEL_PATH", value = "/opt/ml/model" }
      ]

      secrets = [
        {
          name      = "OPENAI_API_KEY"
          valueFrom = aws_secretsmanager_secret.openai_api_key[0].arn
        }
      ]

      log_configuration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ecs[0].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      health_check = {
        command     = ["CMD-SHELL", "python -c 'import urllib.request; urllib.request.urlopen(\"http://localhost:${var.container_port}/api/v1/health\")' || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }
    }
  }

  load_balancer = {
    service = {
      target_group_arn = module.alb[0].target_groups["ecs"].arn
      container_name   = "backend-orchestrator"
      container_port   = var.container_port
    }
  }

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# OpenSearch Serverless
# ------------------------------------------------------------------------------
resource "aws_opensearchserverless_vpc_endpoint" "this" {
  count              = var.enable_aoss ? 1 : 0
  name               = "${local.short_name}-vpce"
  vpc_id             = module.vpc[0].vpc_id
  subnet_ids         = module.vpc[0].private_subnets
  security_group_ids = [aws_security_group.opensearch_endpoint[0].id]
}

resource "aws_opensearchserverless_security_policy" "encryption" {
  count       = var.enable_aoss ? 1 : 0
  name        = "${local.short_name}-enc"
  type        = "encryption"
  description = "Encryption policy for the search collection"

  policy = jsonencode({
    Rules = [
      {
        ResourceType = "collection"
        Resource = [
          "collection/${local.short_name}-search"
        ]
      }
    ]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "network" {
  count       = var.enable_aoss ? 1 : 0
  name        = "${local.short_name}-net"
  type        = "network"
  description = "Restrict collection access to the VPC endpoint"

  policy = jsonencode([
    {
      Description = "VPC endpoint access only"
      Rules = [
        {
          ResourceType = "collection"
          Resource = [
            "collection/${local.short_name}-search"
          ]
        }
      ]
      AllowFromPublic = false
      SourceVPCEs = [
        aws_opensearchserverless_vpc_endpoint.this[0].id
      ]
    }
  ])
}

resource "aws_opensearchserverless_access_policy" "ecs_task" {
  count       = var.enable_aoss ? 1 : 0
  name        = "${local.short_name}-data"
  type        = "data"
  description = "Grant ECS task role access to the search collection"

  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "collection"
          Resource = [
            "collection/${local.short_name}-search"
          ]
          Permission = [
            "aoss:CreateCollectionItems",
            "aoss:DeleteCollectionItems",
            "aoss:UpdateCollectionItems",
            "aoss:DescribeCollectionItems"
          ]
        },
        {
          ResourceType = "index"
          Resource = [
            "index/${local.short_name}-search/*"
          ]
          Permission = [
            "aoss:CreateIndex",
            "aoss:DeleteIndex",
            "aoss:UpdateIndex",
            "aoss:DescribeIndex",
            "aoss:ReadDocument",
            "aoss:WriteDocument"
          ]
        }
      ]
      Principal = [
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.existing_task_role_name}"
      ]
    }
  ])
}

resource "aws_opensearchserverless_collection" "this" {
  count            = var.enable_aoss ? 1 : 0
  name             = "${local.short_name}-search"
  type             = "SEARCH"
  standby_replicas = "DISABLED"

  depends_on = [
    aws_opensearchserverless_security_policy.encryption[0],
    aws_opensearchserverless_security_policy.network[0]
  ]
}
