# T03 Proof Summary — Release SBOM Attachment & Fly Deploy Migration

## Results

| # | Type | Description | Status |
|---|------|-------------|--------|
| 1 | file | fly-deploy.yml contains --image ghcr.io/norrietaylor/distillery and workflow_run trigger | PASS |
| 2 | file | fly-deploy.yml does not contain --remote-only | PASS |
| 3 | file | supply-chain.yml contains softprops/action-gh-release step | PASS |

## Requirements Coverage

| Req | Description | Verified |
|-----|-------------|----------|
| R03.1 | Upload SBOMs to GitHub Release via softprops/action-gh-release@v2 on v* tags | Yes |
| R03.2 | Upload Grype report alongside SBOM to GitHub Release | Yes |
| R03.3 | fly-deploy.yml uses --image ghcr.io/norrietaylor/distillery:sha-{SHORT_SHA} | Yes |
| R03.4 | fly-deploy.yml uses workflow_run trigger from Supply Chain Security workflow | Yes |
| R03.5 | fly-deploy.yml removed --remote-only and --build-arg BUILD_SHA | Yes |
| R03.6 | supply-chain.yml passes BUILD_SHA=${{ github.sha }} as build arg | Yes |

## Notes

- `fly-deploy.yml` uses `workflow_run` on branch `main` with `conclusion == 'success'` guard.
- `workflow_dispatch` retained for manual deploys (uses `github.sha` fallback for SHORT_SHA).
- `contents: write` permission added to supply-chain.yml to allow release asset uploads.
- Release attachment is conditional on `startsWith(github.ref, 'refs/tags/v')`.
