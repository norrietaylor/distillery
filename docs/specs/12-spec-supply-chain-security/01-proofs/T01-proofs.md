# T01 Proof Summary — Supply Chain Scanning Workflow (PR Gate)

## Results

| # | Type | Description | Status |
|---|------|-------------|--------|
| 1 | file | `.github/workflows/supply-chain.yml` contains `anchore/sbom-action` and `anchore/scan-action` | PASS |
| 2 | file | `.grype.yaml` exists at repo root with documented structure | PASS |
| 3 | cli  | Workflow YAML syntax validation (actionlint unavailable, used Python yaml.safe_load) | PASS |

## Requirements Coverage

| Req | Description | Verified |
|-----|-------------|----------|
| R01.1 | Triggers on PR (main), push (main, v* tags) | Yes |
| R01.2 | Build matrix with fly (prefect commented out) | Yes |
| R01.3 | docker/build-push-action with load:true, push:false for PRs | Yes |
| R01.4 | anchore/sbom-action@v0 with cyclonedx-json format | Yes |
| R01.5 | anchore/scan-action@v4 with fail-build:true, severity-cutoff:high | Yes |
| R01.6 | upload-artifact@v4 for SBOM and Grype report (30-day retention) | Yes |
| R01.7 | .grype.yaml with documented structure and empty ignores | Yes |
| R01.8 | Permissions: contents:read, packages:write, id-token:write, attestations:write | Yes |

## Notes

- `actionlint` is not available in this environment. Full GitHub Actions semantic validation will occur on first PR push.
- The workflow is designed to be extended in T02 (signing/attestation) and T03 (release assets/Fly migration).
- Prefect Dockerfile matrix entry is commented out, ready for future activation.
