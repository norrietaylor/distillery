# T02 Proof Summary — Container Signing & Attestation (Main/Tag Push)

## Results

| # | Type | Description | Status |
|---|------|-------------|--------|
| 1 | file | Workflow contains cosign sign, cosign attest (cyclonedx, vuln), and attest-build-provenance | PASS |
| 2 | cli  | cosign verify against published image | BLOCKED (requires CI run on main) |

## Requirements Coverage

| Req | Description | Verified |
|-----|-------------|----------|
| R02.1 | Push image to GHCR with docker/build-push-action push:true | Yes (line 126) |
| R02.2 | Tags: latest (main), sha-{7char} (always), {tag} (on tag) | Yes (lines 107-115) |
| R02.3 | Cosign installed via sigstore/cosign-installer@v3 | Yes (line 139) |
| R02.4 | cosign sign --yes with keyless OIDC | Yes (line 146) |
| R02.5 | cosign attest --type cyclonedx with SBOM predicate | Yes (lines 154-157) |
| R02.6 | cosign attest --type vuln with Grype report predicate | Yes (lines 164-167) |
| R02.7 | actions/attest-build-provenance@v2 for SLSA | Yes (line 172) |
| R02.8 | docker/login-action@v3 with GITHUB_TOKEN | Yes (lines 99-104) |
| R02.9 | Digest extracted from push step output | Yes (5 references to steps.push.outputs.digest) |

## Notes

- All signing/attestation steps are conditional on `github.event_name == 'push'` — they do not run on PRs.
- The `cosign verify` proof is BLOCKED because no image has been pushed yet. It will be verifiable after first merge to main.
- Image is rebuilt for push (separate build-push-action step) to get the digest. The local-load build remains for scanning.
