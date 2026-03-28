# T02: AWS Infrastructure (Terraform) - Proof Summary

## Task

Provision all AWS resources via Terraform with configurable endpoint (Function URL or API Gateway).

## Proof Artifacts

| # | Type | Description | Status | File |
|---|------|-------------|--------|------|
| 1 | cli | `terraform validate` | BLOCKED | T02-01-cli.txt |
| 2 | cli | `terraform fmt -check` | BLOCKED | T02-02-cli.txt |
| 3 | cli | `terraform plan` with function_url | BLOCKED | T02-03-cli.txt |
| 4 | cli | `terraform plan` with api_gateway | BLOCKED | T02-04-cli.txt |
| 5 | file | outputs.tf contains required outputs | PASS | T02-05-file.txt |

## Environment Note

The terraform CLI (>= 1.5) is not installed in the execution environment. Proofs 1-4 are
BLOCKED pending manual validation on a machine with terraform and AWS credentials configured.
All Terraform files follow HCL syntax conventions and use documented AWS provider resources.

## Files Created

- `terraform/versions.tf` - AWS provider ~> 5.0, Terraform >= 1.5
- `terraform/variables.tf` - All configurable inputs with defaults and descriptions
- `terraform/backend.tf` - Remote state in S3 with DynamoDB locking
- `terraform/main.tf` - S3 bucket, ECR repo, Lambda function, IAM role + policies, Secrets Manager
- `terraform/endpoint.tf` - Function URL (default) or API Gateway v2 + custom domain
- `terraform/outputs.tf` - endpoint_url, s3_bucket_name, ecr_repository_url, lambda_function_name
- `terraform/bootstrap/main.tf` - One-time setup for state bucket and lock table

## Deliverable Checklist

- [x] terraform/main.tf with all required resources
- [x] terraform/variables.tf with all inputs
- [x] terraform/outputs.tf with 4 required outputs
- [x] terraform/endpoint.tf with function_url and api_gateway modes
- [x] terraform/backend.tf with S3 + DynamoDB
- [x] terraform/versions.tf with provider pins
- [x] terraform/bootstrap/ for state bucket bootstrap
- [ ] terraform validate (requires terraform CLI)
- [ ] terraform fmt -check (requires terraform CLI)
