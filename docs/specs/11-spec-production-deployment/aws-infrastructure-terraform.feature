# Source: docs/specs/11-spec-production-deployment/11-spec-production-deployment.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: AWS Infrastructure (Terraform)

  Scenario: Terraform configuration is valid
    Given the terraform/ directory exists at the repository root
    When "terraform validate" is run in the terraform/ directory
    Then the command exits with code 0
    And the output contains "Success"

  Scenario: Terraform files are properly formatted
    Given the terraform/ directory contains .tf files
    When "terraform fmt -check" is run in the terraform/ directory
    Then the command exits with code 0
    And no files are listed as needing formatting

  Scenario: Function URL plan produces valid infrastructure
    Given the terraform/ directory is initialized
    When "terraform plan" is run with variable endpoint_type set to "function_url"
    Then the command exits with code 0
    And the plan includes an aws_lambda_function resource
    And the plan includes an aws_lambda_function_url resource
    And the plan includes an aws_s3_bucket resource with versioning
    And the plan includes an aws_ecr_repository resource
    And the plan includes an aws_secretsmanager_secret resource

  Scenario: API Gateway plan produces valid infrastructure with custom domain
    Given the terraform/ directory is initialized
    When "terraform plan" is run with endpoint_type "api_gateway" and custom_domain "distillery.example.com"
    Then the command exits with code 0
    And the plan includes an aws_apigatewayv2_api resource
    And the plan includes an aws_acm_certificate resource
    And the plan includes an aws_route53_record resource

  Scenario: Lambda is configured with correct defaults
    Given the terraform/ directory is initialized
    When "terraform plan" is run with default variables
    Then the planned Lambda function has memory set to 2048
    And the planned Lambda function has timeout set to 300
    And the planned Lambda function has provisioned concurrency set to 1

  Scenario: Terraform outputs include required values
    Given the terraform/ directory is initialized
    When "terraform plan" is run with default variables
    Then the plan defines output "endpoint_url"
    And the plan defines output "s3_bucket_name"
    And the plan defines output "ecr_repository_url"
    And the plan defines output "lambda_function_name"

  Scenario: Bootstrap configuration creates state resources
    Given the terraform/bootstrap/ directory exists
    When "terraform validate" is run in the terraform/bootstrap/ directory
    Then the command exits with code 0
    And the bootstrap configuration defines an S3 bucket for state storage
    And the bootstrap configuration defines a DynamoDB table for state locking
