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
