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
  description = "OpenAI API key stored in Secrets Manager (placeholder is safe when the app does not call OpenAI directly)"
  type        = string
  sensitive   = true
  default     = "placeholder-not-configured"
}

# ------------------------------------------------------------------------------
# SageMaker / Billing
# ------------------------------------------------------------------------------
# MODIFIED: Qwen2.5-7B-Instruct-AWQ for g4dn 16GB VRAM (FP16 needs ml.g5.xlarge)
variable "sagemaker_model_id" {
  description = "Hugging Face model ID for the SageMaker LLM endpoint (AWQ for ml.g4dn.xlarge)"
  type        = string
  default     = "Qwen/Qwen2.5-7B-Instruct-AWQ"
}

variable "sagemaker_container_image" {
  description = "AWS Deep Learning Container image for the SageMaker vLLM endpoint"
  type        = string
  default     = "763104351884.dkr.ecr.ap-southeast-2.amazonaws.com/huggingface-vllm:0.25.1-transformers5.10.2-gpu-py312-cu130-ubuntu22.04"
}

variable "sagemaker_instance_type" {
  description = "SageMaker endpoint instance type (g4dn+AWQ default; use ml.g5.xlarge for FP16)"
  type        = string
  default     = "ml.g4dn.2xlarge"
}

# MODIFIED: cu130 images require InferenceAmiVersion or container dies with no logs
variable "sagemaker_inference_ami_version" {
  description = "Required for huggingface-vllm cu130+ tags (HF/AWS guidance)"
  type        = string
  default     = "al2-ami-sagemaker-inference-gpu-3-1"
}

variable "sagemaker_max_model_len" {
  description = "Optional vLLM max model length (empty = model default)"
  type        = string
  default     = "4096"
}

variable "sagemaker_gpu_memory_utilization" {
  description = "vLLM GPU memory utilization fraction"
  type        = string
  default     = "0.90"
}

variable "deploy_sagemaker_model" {
  description = "When true, create the SageMaker model, endpoint config, and endpoint"
  type        = bool
  default     = false
}

variable "sagemaker_execution_role_arn" {
  description = "Optional pre-existing IAM role ARN for SageMaker execution. If empty, a role is created."
  type        = string
  default     = ""
}

variable "sagemaker_model_bucket_name" {
  description = "S3 bucket for SageMaker model artifacts"
  type        = string
  default     = "backend-orchestrator-models-808454010747"
}

