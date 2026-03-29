# T04 Proof Summary — GitHub Actions CD Pipeline

**Task:** T04: GitHub Actions CD Pipeline
**Spec:** docs/specs/11-spec-production-deployment/11-spec-production-deployment.md (Unit 4)
**Date:** 2026-03-28
**Worker:** worker-4 (claude-sonnet-4-6)

## Deliverables

Created `.github/workflows/deploy.yml` — a GitHub Actions CD pipeline that:

1. Triggers on `workflow_run` (CI passes on main) and `workflow_dispatch` (manual)
2. Runs the full test suite with 80% coverage threshold before deploying
3. Builds and pushes a Docker image to ECR with a timestamped tag
4. Authenticates to AWS via OIDC (no long-lived access keys)
5. Updates the Lambda function to the new container image
6. Waits for Lambda update and provisioned concurrency to stabilize
7. Runs a 3-step smoke test: `/health`, MCP `initialize`, `tools/list` (21 tools)
8. Writes a deployment summary to the GitHub Actions step summary
9. Emits an error annotation on failure

All AWS infrastructure identifiers (account ID, region, ECR repo, Lambda name, endpoint URL) are sourced from GitHub Actions variables — nothing hardcoded.

## Proof Artifacts

| File | Type | Status | Description |
| ---- | ---- | ------ | ----------- |
| T04-01-file.txt | file | PASS | deploy.yml exists with correct triggers and all required steps |
| T04-02-file.txt | file | PASS | Smoke test steps present; OIDC auth configured; no hardcoded AWS IDs |
| T04-03-cli.txt | cli | PASS | YAML syntax valid; trigger/jobs/permissions structure correct |

## Feature Scenarios Covered

- Deploy workflow triggers on push to main: PASS (workflow_run on CI success)
- Deploy workflow runs tests before deployment: PASS (test job with --cov-fail-under=80)
- Build and push Docker image to ECR: PASS (aws-actions/amazon-ecr-login + docker build/push)
- AWS authentication via OIDC: PASS (aws-actions/configure-aws-credentials with role-to-assume)
- Lambda function update: PASS (aws lambda update-function-code + wait function-updated)
- Smoke test /health: PASS (curl to /health, validates status=ok)
- Smoke test MCP initialize: PASS (JSON-RPC initialize, validates result field)
- Smoke test tools/list 21 tools: PASS (JSON-RPC tools/list, validates count=21)
- Failure notification: PASS (Notify on failure step with error annotation + summary)
- Configurable via GitHub Actions variables: PASS (vars.AWS_ACCOUNT_ID, vars.AWS_REGION, vars.ECR_REPOSITORY, vars.LAMBDA_FUNCTION_NAME, vars.ENDPOINT_URL)
- Terraform state NOT applied by CD: PASS (no terraform commands in workflow)
