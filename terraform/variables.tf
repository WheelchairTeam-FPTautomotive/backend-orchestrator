# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------
variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project identifier used in resource naming"
  type        = string
  default     = "backend-orchestrator"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

# ------------------------------------------------------------------------------
# Network
# ------------------------------------------------------------------------------
variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (ALB)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for private subnets (ECS tasks + OpenSearch VPC endpoint)"
  type        = list(string)
  default     = ["10.0.3.0/24", "10.0.4.0/24"]
}

# ------------------------------------------------------------------------------
# ECS / Container
# ------------------------------------------------------------------------------
variable "container_port" {
  description = "Port exposed by the backend-orchestrator container"
  type        = number
  default     = 8000
}

variable "image_tag" {
  description = "Container image tag to deploy"
  type        = string
  default     = "latest"
}

variable "desired_count" {
  description = "Number of Fargate tasks to run"
  type        = number
  default     = 1
}

variable "fargate_cpu" {
  description = "Fargate task CPU units"
  type        = number
  default     = 256
}

variable "fargate_memory" {
  description = "Fargate task memory (MiB)"
  type        = number
  default     = 512
}

variable "log_level" {
  description = "Application log level"
  type        = string
  default     = "INFO"
}

variable "core_ai_url" {
  description = "URL of the downstream KMS Core AI RAG service"
  type        = string
  default     = "http://CHANGE_ME:8001/api/v1/search"
}

variable "openai_api_key" {
  description = "OpenAI API key stored in Secrets Manager"
  type        = string
  sensitive   = true
  default     = ""
}
