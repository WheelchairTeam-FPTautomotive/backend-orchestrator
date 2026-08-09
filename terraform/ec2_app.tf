# ------------------------------------------------------------------------------
# Locked v1 compute: one EC2 on the default VPC (no NAT gateway — Budget).
# gateway + Core + Chroma + VieNeu are installed by Ansible (ec2_kms_stack).
# ------------------------------------------------------------------------------

variable "enable_ec2" {
  description = "Provision the single app EC2 host (locked v1 path)"
  type        = bool
  default     = true
}

variable "ec2_instance_type" {
  description = "EC2 instance type for gateway+Core+VieNeu"
  type        = string
  default     = "t3.xlarge"
}

variable "ec2_key_name" {
  description = "Existing EC2 key pair name for SSH (empty = no key)"
  type        = string
  default     = ""
}

variable "ssh_ingress_cidr" {
  description = "CIDR allowed to SSH (port 22). Restrict to your IP/32 in prod."
  type        = string
  default     = "0.0.0.0/0"
}

variable "app_ingress_cidr" {
  description = "CIDR allowed to hit gateway :8000 (cockpit / demos)"
  type        = string
  default     = "0.0.0.0/0"
}

variable "create_ec2_instance_profile" {
  description = "Create IAM role+instance profile for Bedrock/S3 (set false if hackathon blocks iam:CreateRole)"
  type        = bool
  default     = true
}

variable "existing_ec2_instance_profile_name" {
  description = "Pre-existing instance profile name when create_ec2_instance_profile=false"
  type        = string
  default     = ""
}

data "aws_ami" "ubuntu_jammy" {
  count       = var.enable_ec2 ? 1 : 0
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_vpc" "default" {
  count   = var.enable_ec2 ? 1 : 0
  default = true
}

data "aws_subnets" "default_public" {
  count = var.enable_ec2 ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
}

resource "aws_security_group" "kms_app" {
  count       = var.enable_ec2 ? 1 : 0
  name_prefix = "${local.short_name}-ec2-"
  description = "KMS one-EC2 app host (gateway 8000, SSH)"
  vpc_id      = data.aws_vpc.default[0].id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_ingress_cidr]
    description = "SSH"
  }

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.app_ingress_cidr]
    description = "Gateway HTTP"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.short_name}-ec2" })
}

resource "aws_iam_role" "kms_ec2" {
  count = var.enable_ec2 && var.create_ec2_instance_profile ? 1 : 0
  name  = "${local.short_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "kms_ec2_bedrock_s3" {
  count = var.enable_ec2 && var.create_ec2_instance_profile ? 1 : 0
  name  = "${local.short_name}-ec2-bedrock-s3"
  role  = aws_iam_role.kms_ec2[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:Converse",
          "bedrock:ConverseStream"
        ]
        Resource = "*"
      },
      {
        Sid    = "ManualsS3Read"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = var.enable_manuals_bucket ? [
          aws_s3_bucket.manuals[0].arn,
          "${aws_s3_bucket.manuals[0].arn}/*"
        ] : ["arn:aws:s3:::*"]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "kms_ec2" {
  count = var.enable_ec2 && var.create_ec2_instance_profile ? 1 : 0
  name  = "${local.short_name}-ec2-profile"
  role  = aws_iam_role.kms_ec2[0].name
  tags  = local.common_tags
}

locals {
  ec2_instance_profile = var.enable_ec2 ? (
    var.create_ec2_instance_profile ? aws_iam_instance_profile.kms_ec2[0].name : var.existing_ec2_instance_profile_name
  ) : ""
}

resource "aws_instance" "kms_app" {
  count = var.enable_ec2 ? 1 : 0

  ami                         = data.aws_ami.ubuntu_jammy[0].id
  instance_type               = var.ec2_instance_type
  subnet_id                   = data.aws_subnets.default_public[0].ids[0]
  vpc_security_group_ids      = [aws_security_group.kms_app[0].id]
  associate_public_ip_address = true
  key_name                    = var.ec2_key_name != "" ? var.ec2_key_name : null
  iam_instance_profile        = local.ec2_instance_profile != "" ? local.ec2_instance_profile : null

  root_block_device {
    volume_size = 40
    volume_type = "gp3"
  }

  user_data = <<-EOF
              #!/bin/bash
              set -euo pipefail
              apt-get update -y
              apt-get install -y docker.io docker-compose-v2 git curl tmux python3
              systemctl enable --now docker
              mkdir -p /opt/kms /etc/kms
              echo "KMS EC2 bootstrap done — run Ansible deploy-ec2-stack.yml" > /opt/kms/BOOTSTRAP.txt
              EOF

  tags = merge(local.common_tags, {
    Name              = "${local.short_name}-app"
    BedrockModelId    = var.bedrock_model_id
    KmsDeployRole     = "gateway-core-chroma-vieneu"
  })
}

resource "aws_eip" "kms_app" {
  count  = var.enable_ec2 ? 1 : 0
  domain = "vpc"
  tags   = merge(local.common_tags, { Name = "${local.short_name}-eip" })
}

resource "aws_eip_association" "kms_app" {
  count         = var.enable_ec2 ? 1 : 0
  instance_id   = aws_instance.kms_app[0].id
  allocation_id = aws_eip.kms_app[0].id
}
