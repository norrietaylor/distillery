# Clarifying Questions — Round 1

## Q1: Auth strategy for Fly.io deployment
**Answer:** GitHub OAuth from day one. Reuse existing GitHubProvider auth with GITHUB_CLIENT_ID/SECRET and DISTILLERY_BASE_URL secrets on Fly.

## Q2: Documentation approach for deploy directory
**Answer:** Per-provider README — deploy/fly/README.md and deploy/prefect/README.md with quickstart steps specific to each platform.

## Q3: Default Fly.io region
**Answer:** Leave blank — user picks region on first deploy.
