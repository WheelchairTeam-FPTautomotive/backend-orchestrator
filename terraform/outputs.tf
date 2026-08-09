output "ec2_public_ip" {
  description = "Elastic IP of the locked one-EC2 app host"
  value       = var.enable_ec2 ? aws_eip.kms_app[0].public_ip : ""
}

output "ec2_instance_id" {
  description = "Instance id of the KMS app host"
  value       = var.enable_ec2 ? aws_instance.kms_app[0].id : ""
}

output "manuals_bucket_name" {
  description = "S3 bucket for OEM PDF manuals (source of record)"
  value       = var.enable_manuals_bucket ? aws_s3_bucket.manuals[0].bucket : ""
}

output "bedrock_model_id" {
  description = "Locked Bedrock answer model id"
  value       = var.bedrock_model_id
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer (legacy ECS)"
  value       = var.enable_ecs ? module.alb[0].dns_name : ""
}

output "ecr_repository_url" {
  description = "URL of the backend-orchestrator ECR repository (legacy ECS)"
  value       = var.enable_ecs ? aws_ecr_repository.backend_orchestrator[0].repository_url : ""
}

output "opensearch_collection_endpoint" {
  description = "Endpoint of the OpenSearch Serverless search collection (legacy)"
  value       = var.enable_aoss ? aws_opensearchserverless_collection.this[0].collection_endpoint : ""
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster (legacy)"
  value       = var.enable_ecs ? module.ecs_cluster[0].cluster_name : ""
}

output "ecs_service_name" {
  description = "Name of the ECS Fargate service (legacy)"
  value       = var.enable_ecs ? module.ecs_service[0].name : ""
}

output "openai_api_key_secret_arn" {
  description = "ARN of the OpenAI API key secret in Secrets Manager (legacy ECS)"
  value       = var.enable_ecs ? aws_secretsmanager_secret.openai_api_key[0].arn : ""
}

output "ecs_log_group_name" {
  description = "CloudWatch log group for the ECS Fargate service task definition"
  value       = var.enable_ecs ? aws_cloudwatch_log_group.ecs_service[0].name : ""
}

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
  value       = var.deploy_sagemaker_model ? aws_vpc_endpoint.sagemaker_runtime[0].dns_entry[0].dns_name : ""
}
