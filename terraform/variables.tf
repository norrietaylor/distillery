variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "endpoint_type" {
  description = "HTTPS endpoint type: 'function_url' (simple) or 'api_gateway' (production with custom domain)"
  type        = string
  default     = "function_url"

  validation {
    condition     = contains(["function_url", "api_gateway"], var.endpoint_type)
    error_message = "endpoint_type must be 'function_url' or 'api_gateway'."
  }
}

variable "custom_domain" {
  description = "Custom domain name for API Gateway endpoint (required when endpoint_type = 'api_gateway')"
  type        = string
  default     = ""
}

variable "lambda_memory" {
  description = "Lambda function memory in MB (DuckDB + VSS requires ~512 MB minimum)"
  type        = number
  default     = 2048
}

variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300
}

variable "provisioned_concurrency" {
  description = "Number of provisioned concurrent Lambda executions (0 to disable)"
  type        = number
  default     = 1
}

variable "state_bucket_name" {
  description = "S3 bucket name for Terraform remote state"
  type        = string
  default     = "distillery-terraform-state"
}

variable "state_lock_table_name" {
  description = "DynamoDB table name for Terraform state locking"
  type        = string
  default     = "distillery-terraform-lock"
}

variable "project_name" {
  description = "Project name used as prefix for resource naming"
  type        = string
  default     = "distillery"
}

variable "environment" {
  description = "Environment name (e.g., production, staging)"
  type        = string
  default     = "production"
}
