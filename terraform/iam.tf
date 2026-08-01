# ------------------------------------------------------------------------------
# Existing IAM Roles (provided by the hackathon environment)
#
# We cannot create new IAM roles or attach inline policies, and we cannot call
# iam:GetRole/iam:ListRoles. We therefore only declare the role-name variables
# here; the ARNs are constructed manually in main.tf.
# ------------------------------------------------------------------------------

variable "existing_task_execution_role_name" {
  description = "Name of the pre-existing IAM role for ECS task execution"
  type        = string
  default     = "ecsTaskExecutionRole"
}

variable "existing_task_role_name" {
  description = "Name of the pre-existing IAM role for ECS tasks"
  type        = string
  default     = "TeamRole"
}
