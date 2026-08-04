output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = module.alb.dns_name
}

output "ecr_repository_url" {
  description = "URL of the backend-orchestrator ECR repository"
  value       = aws_ecr_repository.backend_orchestrator.repository_url
}

output "opensearch_collection_endpoint" {
  description = "Endpoint of the OpenSearch Serverless search collection"
  value       = aws_opensearchserverless_collection.this.collection_endpoint
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = module.ecs_cluster.cluster_name
}

output "ecs_service_name" {
  description = "Name of the ECS Fargate service"
  value       = module.ecs_service.name
}

output "openai_api_key_secret_arn" {
  description = "ARN of the OpenAI API key secret in Secrets Manager"
  value       = aws_secretsmanager_secret.openai_api_key.arn
}

output "ecs_log_group_name" {
  description = "CloudWatch log group for the ECS Fargate service task definition"
  value       = aws_cloudwatch_log_group.ecs_service.name
}

# ------------------------------------------------------------------------------
# SageMaker / Billing
# ------------------------------------------------------------------------------
output "sagemaker_model_bucket_name" {
  description = "S3 bucket for SageMaker model artifacts"
  value       = aws_s3_bucket.model_artifacts.bucket
}

output "sagemaker_execution_role_arn" {
  description = "IAM role ARN used by the SageMaker endpoint"
  value       = local.sagemaker_execution_role_arn
}

output "sagemaker_endpoint_name" {
  description = "Name of the SageMaker LLM endpoint"
  value       = var.deploy_sagemaker_model ? aws_sagemaker_endpoint.llm[0].name : ""
}

output "sagemaker_endpoint_arn" {
  description = "ARN of the SageMaker LLM endpoint"
  value       = var.deploy_sagemaker_model ? aws_sagemaker_endpoint.llm[0].arn : ""
}

output "sagemaker_runtime_vpc_endpoint_dns" {
  description = "DNS name of the SageMaker Runtime VPC endpoint"
  value       = aws_vpc_endpoint.sagemaker_runtime.dns_entry[0].dns_name
}

