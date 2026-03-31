# 12-spec-supply-chain-security

## Introduction/Overview

Add supply chain security to the Distillery CI pipeline: dependency and container vulnerability scanning (Grype), CycloneDX SBOM generation (Syft), keyless container signing (Cosign/Sigstore), and in-toto attestations. This closes the gap between "code passes tests" and "the deployed artifact is verifiably safe and traceable." Resolves [#65](https://github.com/norrietaylor/distillery/issues/65).

## Goals

1. **Block vulnerable code from merging** — fail PR builds on critical/high severity vulnerabilities in Python dependencies or container image packages.
2. **Produce machine-readable SBOMs** — generate CycloneDX JSON SBOMs for every built image, attached as CI artifacts on PRs and to GitHub Releases on tags.
3. **Cryptographically sign images** — keyless Cosign signing via Sigstore OIDC for all images pushed to `ghcr.io/norrietaylor/distillery`.
4. **Attach verifiable attestations** — in-toto attestations (SBOM, vulnerability scan, SLSA provenance) on the OCI manifest.
5. **Unify the deploy flow** — build images once in CI, push to GHCR, and have Fly.io deploy from the signed GHCR image (single source of truth).

## User Stories

- As a **maintainer**, I want PR builds to fail if a critical/high vulnerability is detected so that insecure code cannot be merged.
- As a **consumer of the image**, I want to run `cosign verify` against the published image so that I can confirm its provenance.
- As a **security auditor**, I want CycloneDX SBOMs attached to GitHub Releases so that I can inspect the software bill of materials for any release.
- As a **maintainer**, I want false-positive vulnerabilities suppressed via `.grype.yaml` so that the pipeline doesn't block on known non-issues.
- As an **operator**, I want Fly.io to deploy from the same signed image that CI built so that there is no divergence between what was scanned and what runs in production.

## Demoable Units of Work

### Unit 1: Supply Chain Scanning Workflow (PR Gate)

**Purpose:** Add a new GitHub Actions workflow that builds the Docker image, generates an SBOM, scans for vulnerabilities, and fails the build on critical/high findings. This runs on every PR and push to main.

**Functional Requirements:**

- The system shall provide a new workflow file `.github/workflows/supply-chain.yml` that triggers on `pull_request` (branches: main) and `push` (branches: main, tags: `v*`).
- The workflow shall use a build matrix to support multiple Dockerfiles (initially `deploy/fly/Dockerfile` only, with `deploy/prefect/Dockerfile` as a commented-out matrix entry for future use).
- The workflow shall build the Docker image using `docker/build-push-action@v5` with `load: true` (local load, no push) for PR builds.
- The workflow shall generate a CycloneDX JSON SBOM from the built image using `anchore/sbom-action@v0` (Syft), output to `sbom-{target}.cdx.json`.
- The workflow shall scan the SBOM using `anchore/scan-action@v4` (Grype) with `fail-build: true` and `severity-cutoff: high`.
- The workflow shall upload the SBOM and Grype scan report as CI artifacts using `actions/upload-artifact@v4` with 30-day retention.
- The workflow shall provide a `.grype.yaml` configuration file at the repository root for false-positive suppression (initially empty ignores list with documentation comments).
- The workflow shall use `GITHUB_TOKEN` permissions: `contents: write` (required for release asset uploads), `packages: write`, `id-token: write`, `attestations: write`.

**Proof Artifacts:**

- File: `.github/workflows/supply-chain.yml` exists and contains `anchore/sbom-action` and `anchore/scan-action` steps
- File: `.grype.yaml` exists at repository root with documented structure
- CLI: `act -j supply-chain` or a dry-run validation confirms workflow syntax is valid (`actionlint` pass)
- Test: Open a PR and observe the supply-chain check running, SBOM artifact uploaded

### Unit 2: Container Signing & Attestation (Main/Tag Push)

**Purpose:** On pushes to main and tag pushes, build and push the image to GHCR, sign it with Cosign keyless signing, and attach in-toto attestations (SBOM, vulnerability scan, SLSA provenance).

**Functional Requirements:**

- The workflow shall, on push to `main` or `v*` tags, push the built image to `ghcr.io/norrietaylor/distillery` using `docker/build-push-action@v5` with `push: true`.
- The workflow shall tag images as: `latest` (main branch), `sha-{7char}` (always), and `{tag}` (on tag push, e.g., `v1.2.3`).
- The workflow shall install Cosign using `sigstore/cosign-installer@v3`.
- The workflow shall sign the pushed image digest using `cosign sign --yes ghcr.io/norrietaylor/distillery@${DIGEST}` (keyless via Sigstore OIDC — no manual keys).
- The workflow shall attach an in-toto SBOM attestation using `cosign attest --yes --type cyclonedx --predicate sbom-{target}.cdx.json ghcr.io/norrietaylor/distillery@${DIGEST}`.
- The workflow shall attach a vulnerability scan attestation using `cosign attest --yes --type vuln --predicate grype-report-{target}.json ghcr.io/norrietaylor/distillery@${DIGEST}`.
- The workflow shall generate SLSA provenance using `actions/attest-build-provenance@v2` attached to the image digest.
- The workflow shall use `docker/login-action@v3` to authenticate to GHCR using `GITHUB_TOKEN`.
- The workflow shall extract the image digest from the build-push-action output for signing/attestation (not a mutable tag).

**Proof Artifacts:**

- CLI: `cosign verify --certificate-oidc-issuer https://token.actions.githubusercontent.com --certificate-identity-regexp "github.com/norrietaylor/distillery" ghcr.io/norrietaylor/distillery:latest` succeeds
- CLI: `cosign verify-attestation --type cyclonedx --certificate-oidc-issuer https://token.actions.githubusercontent.com --certificate-identity-regexp "github.com/norrietaylor/distillery" ghcr.io/norrietaylor/distillery:latest` returns SBOM predicate
- File: Workflow contains `cosign sign`, `cosign attest --type cyclonedx`, `cosign attest --type vuln`, and `actions/attest-build-provenance` steps

### Unit 3: Release SBOM Attachment & Fly Deploy Migration

**Purpose:** On tag pushes, attach SBOMs to the GitHub Release. Migrate `fly-deploy.yml` to deploy from the signed GHCR image instead of building remotely.

**Functional Requirements:**

- The workflow shall, on `v*` tag pushes, upload SBOM files to the corresponding GitHub Release using `softprops/action-gh-release@v2` with the SBOM as an asset.
- The workflow shall upload the Grype vulnerability report alongside the SBOM to the GitHub Release.
- The `fly-deploy.yml` workflow shall be updated to deploy from the GHCR image: `flyctl deploy -c deploy/fly/fly.toml --image ghcr.io/norrietaylor/distillery:{tag-or-sha}`.
- The `fly-deploy.yml` workflow shall trigger after the supply-chain workflow completes successfully on main (using `workflow_run` trigger or by being called as a reusable workflow).
- The `fly-deploy.yml` workflow shall remove `--remote-only` and `--build-arg BUILD_SHA` (the image is pre-built; BUILD_SHA is baked in during the supply-chain build).
- The supply-chain workflow shall pass `BUILD_SHA=${{ github.sha }}` as a build arg to maintain the existing build SHA in the image.

**Proof Artifacts:**

- CLI: `gh release view v{X.Y.Z} --json assets` shows `sbom-fly.cdx.json` and `grype-report-fly.json` attached
- File: `fly-deploy.yml` contains `--image ghcr.io/norrietaylor/distillery` and does not contain `--remote-only`
- File: `fly-deploy.yml` uses `workflow_run` or `workflow_call` trigger from supply-chain workflow
- Test: Push a tag, observe GitHub Release with SBOM assets and Fly deployment from GHCR image

## Non-Goals (Out of Scope)

- **Prefect Dockerfile**: No `deploy/prefect/Dockerfile` exists. The workflow matrix is designed to accommodate it when created, but this spec does not create one.
- **Runtime security scanning**: No runtime container monitoring or Falco-style detection.
- **Private key management**: Cosign uses keyless signing only (Sigstore OIDC). No manual key rotation or KMS integration.
- **Dependency pinning or lockfile generation**: This spec scans what exists; it does not introduce `pip-compile` or lockfiles.
- **SLSA Level 3+**: We target SLSA provenance attestation but not hermetic builds or isolated build environments beyond what GitHub Actions provides.
- **Notification/alerting**: No Slack/email alerts on vulnerability findings — GitHub's existing check status is sufficient.

## Design Considerations

No UI/UX requirements. All artifacts are CI-generated files and OCI attestations consumed by CLI tools (`cosign verify`, `grype`, `syft`).

## Repository Standards

- **Commit format**: Conventional Commits — `feat(ci): description`
- **Workflow naming**: Lowercase with hyphens (e.g., `supply-chain.yml`)
- **Existing patterns**: `ci.yml` uses `actions/checkout@v4`, `actions/upload-artifact@v4` — follow the same action version pinning convention
- **Config at root**: `.grype.yaml` follows the pattern of other root-level config files (`.dockerignore`, `pyproject.toml`)

## Technical Considerations

- **GHCR authentication**: Uses `GITHUB_TOKEN` (automatic), no additional secrets needed.
- **Cosign keyless**: Relies on Sigstore OIDC identity from GitHub Actions. Requires `id-token: write` permission.
- **Build matrix**: Initially `[{target: fly, dockerfile: deploy/fly/Dockerfile}]`. Adding Prefect later is a one-line matrix addition.
- **Digest pinning**: All signing and attestation operations target `@sha256:...` digests, not mutable tags, to prevent TOCTOU issues.
- **Workflow dependency**: `fly-deploy.yml` must wait for the supply-chain workflow to complete. `workflow_run` trigger on `supply-chain` workflow completion is the cleanest approach.
- **Build arg passthrough**: `BUILD_SHA=${{ github.sha }}` must be passed during `docker/build-push-action` to maintain the existing `DISTILLERY_BUILD_SHA` env var in the image.
- **Artifact retention**: 30 days for PR artifacts, permanent for release assets.

## Security Considerations

- **No secrets required**: Cosign keyless signing and GHCR push both use `GITHUB_TOKEN`. No additional secrets to manage.
- **OIDC identity**: The signing identity is the GitHub Actions workflow run itself, verifiable via `--certificate-oidc-issuer https://token.actions.githubusercontent.com`.
- **Transparency log**: Cosign keyless signs are recorded in the Rekor transparency log by default. This is public — acceptable since the repository is public.
- **Grype DB updates**: Grype fetches its vulnerability database on each run. CI must have outbound internet access (standard for GitHub Actions).
- **False-positive suppression**: `.grype.yaml` must be reviewed in PRs to prevent legitimate vulnerabilities from being suppressed.

## Success Metrics

- Every PR has a passing/failing supply-chain check with SBOM artifact.
- Every image pushed to GHCR is signed and has SBOM + vuln attestations.
- `cosign verify` and `cosign verify-attestation` succeed for published images.
- Every GitHub Release (tag) has SBOM and vulnerability report attached.
- Fly.io deploys from the GHCR image (no more `--remote-only` builds).
- Zero manual key management — fully keyless.

## Open Questions

1. **Grype DB caching**: Should we cache the Grype vulnerability database between CI runs to speed up scans, or is fresh-fetch acceptable? (Default: fresh-fetch for maximum accuracy.)
2. **Image tag strategy for Fly**: Should Fly deploy the `latest` tag or the specific `sha-{commit}` tag? Using SHA is more deterministic but requires extracting it from the supply-chain workflow output.
