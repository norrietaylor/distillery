# 19-spec-gitlab-auth

## Introduction/Overview

Distillery's HTTP transport currently supports one identity provider: GitHub OAuth (`server.auth.provider: github`), with an optional API-backed org-membership gate. This spec adds GitLab — both self-hosted instances and gitlab.com — as an alternative identity provider via OpenID Connect (OIDC), using FastMCP's generic `OIDCProxy`. GitLab is an identity gate only, exactly like GitHub today: the server never accesses the user's GitLab resources.

Design decisions were settled in a grilling session on 2026-07-06; the load-bearing one is recorded in [ADR-0001](../../adr/0001-gitlab-auth-claim-based-group-gating.md). Vocabulary is in the root `CONTEXT.md`.

## Goals

1. **`server.auth.provider: gitlab`** — a per-deployment alternative to `github`. Exactly one identity provider per deployment; no mixed-provider support.
2. **OIDC-based, no bespoke API client** — use FastMCP's `OIDCProxy` against GitLab's discovery document (`https://<instance>/.well-known/openid-configuration`), scopes `openid profile email`.
3. **Claim-based group gating** — authorization reads the OIDC `groups` claim at login. No GitLab equivalent of `OrgMembershipChecker` (see ADR-0001 for the revocation-latency trade-off, accepted).
4. **Single identity namespace** — GitLab's `nickname` (username) maps into the existing `login` claim so authorship, audit, and the machine-token path work unchanged.
5. **Machine tokens unchanged** — the pre-shared machine-token path is provider-agnostic and must keep working under `provider: gitlab`.

## Configuration

```yaml
server:
  auth:
    provider: gitlab                  # new value alongside 'github' | 'none'
    instance_url: https://gitlab.example.com   # new; default https://gitlab.com
    client_id_env: DISTILLERY_GITLAB_CLIENT_ID
    client_secret_env: DISTILLERY_GITLAB_CLIENT_SECRET
    allowed_groups: [acme]            # GitLab group full-paths; gitlab-only key
```

- `allowed_groups` is the GitLab spelling of the gate list; `allowed_orgs` stays GitHub-only. Internally both normalize to one "allowed memberships" concept — the gate logic is not duplicated, only the claim/source plumbing differs.
- **Subtree matching**: an allowed group admits itself and all descendants by path segment (`acme` matches `acme/dev`, not `acme-corp`).
- **Empty `allowed_groups`**: permitted for self-hosted instances (instance login is the boundary — open-access mode, same semantics as empty `allowed_orgs` today).
- **Startup validation**: when `instance_url` resolves to gitlab.com, the server refuses to start with an empty `allowed_groups` (an authenticated gitlab.com user is anyone on the internet).
- `DISTILLERY_BASE_URL` remains required, as for GitHub.

## Functional Requirements

1. Config parsing/validation accepts `provider: gitlab`, `instance_url`, `allowed_groups`; rejects `allowed_groups` under `provider: github` and `allowed_orgs` under `provider: gitlab`; enforces the gitlab.com non-empty-groups rule.
2. A GitLab provider builder (parallel to `build_github_auth`) constructs an `OIDCProxy` against `instance_url`, reading client id/secret from the configured env vars, wiring machine tokens and the audit callback identically to the GitHub path.
3. Claims extraction maps `nickname` → `login` (plus `name`, `email`) and evaluates the `groups` claim against `allowed_groups` with subtree matching; a user matching no allowed group is denied at login (audit event emitted).
4. Token lifetime is bounded (hours, not weeks) so group removal takes effect on expiry; immediate lockout is "block the user in GitLab" — documented, not coded.
5. `mypy --strict` clean; unit tests cover claim mapping, subtree matching (incl. the `acme-corp` non-match), empty-groups self-hosted pass-through, gitlab.com validation failure, and machine-token bypass.

### Verification note (resolve during implementation, before building on it)

Confirm how FastMCP's `OIDCProxy` exposes userinfo/id_token claims for embedding into the issued JWT (the GitHub path overrides `_extract_upstream_claims`), and confirm which claim GitLab populates with full group paths for the target versions (`groups` in userinfo vs `groups_direct` in the id_token). Do this as a thin tracer slice against a real GitLab instance first.

## Out of Scope

- Mixed GitHub+GitLab logins on one deployment.
- Per-request membership re-verification for GitLab (rejected — ADR-0001).
- GitLab access-level distinctions (Guest vs Developer etc.) — any group member passes the gate.
- `distill_ops` deployment configs (separate repo, separate change).

## Deliverables

- Code + tests as above.
- Docs site: GitLab setup page alongside the GitHub auth docs.
- `/setup` skill: hosted-transport onboarding must handle a GitLab-backed server, not assume GitHub.
