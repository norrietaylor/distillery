output "endpoint_url" {
  description = "HTTPS endpoint URL for the MCP server"
  value = var.endpoint_type == "function_url" ? (
    length(aws_lambda_function_url.mcp_server) > 0 ? aws_lambda_function_url.mcp_server[0].function_url : ""
    ) : (
    var.custom_domain != "" ? "https://${var.custom_domain}" : (
      length(aws_apigatewayv2_api.mcp_server) > 0 ? aws_apigatewayv2_api.mcp_server[0].api_endpoint : ""
    )
  )
}

output "s3_bucket_name" {
  description = "S3 bucket name for DuckDB storage"
  value       = aws_s3_bucket.storage.id
}

output "ecr_repository_url" {
  description = "ECR repository URL for the Docker container image"
  value       = aws_ecr_repository.app.repository_url
}

output "lambda_function_name" {
  description = "Lambda function name for the MCP server"
  value       = aws_lambda_function.mcp_server.function_name
}
