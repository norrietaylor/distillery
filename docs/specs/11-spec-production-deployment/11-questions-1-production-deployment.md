---
round: 1
spec: 11-spec-production-deployment
---

# Questions — Round 1

## Scope & Boundaries

1. **AWS account**: Do you already have an AWS account set up with IAM credentials ready, or does the spec need to cover account bootstrap?

2. **Domain**: The epic mentions `distillery.norrietaylor.com` — do you own this domain and want to configure it, or should we use a Lambda Function URL / API Gateway auto-generated URL for now?

3. **Container vs zip**: The epic recommends container images for Lambda. Confirm: Docker container image deployed to ECR, or Lambda zip package?

4. **Terraform state backend**: The epic mentions S3 + DynamoDB for remote state. Do you already have a state bucket, or should the spec include bootstrapping that?

## Architecture Decisions

5. **API Gateway vs Lambda Function URL**: API Gateway provides custom domains, WAF, throttling but adds cost/complexity. Lambda Function URL is simpler but fewer features. Which?

6. **Staging environment**: The epic lists this as optional. Include in spec or defer?

7. **FastMCP Cloud decommission**: Should the spec include removing the `able-red-cougar.fastmcp.app` deployment, or leave it running alongside the AWS deployment?
