# Clarifying Questions — Round 1

## Q1: Scope — Prefect Dockerfile
**Question:** No deploy/prefect/Dockerfile exists. Scope to Fly.io only or create one?
**Answer:** Skip Prefect for now. Design the workflow matrix to support it, but only wire up Fly.

## Q2: Deploy Flow — GHCR-first
**Question:** Modify fly-deploy.yml to pull from GHCR instead of building remotely?
**Answer:** Yes, GHCR-first. Build in CI → push to GHCR → sign/attest → Fly deploys from GHCR.

## Q3: Releases — Trigger mechanism
**Question:** Tag push trigger or manual release workflow?
**Answer:** Tag push trigger. Workflow triggers on v* tags, creates/updates GitHub Release with SBOMs.

## Q4: Workflow — Separate or integrated
**Question:** Separate workflow file or extend ci.yml?
**Answer:** Separate file: .github/workflows/supply-chain.yml.

## Q5: Fly Deploy Update
**Question:** Update fly-deploy.yml to use GHCR image in this spec or follow-up?
**Answer:** Update fly-deploy.yml in this spec.
