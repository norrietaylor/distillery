# GitLab auth gates on the OIDC groups claim, not an API-backed membership checker

Status: accepted

When `server.auth.provider` is `gitlab`, the identity gate reads the user's
GitLab group memberships from the OpenID Connect (OIDC) `groups` claim at
login and bakes the result into the FastMCP-issued token — unlike the GitHub
provider, which re-verifies org membership against the GitHub API per request
via `OrgMembershipChecker` (TTL cache, optional server PAT). We chose the
claim because GitLab delivers memberships in the token for free, which
eliminates the checker/cache/server-token machinery entirely for GitLab
deployments.

## Consequences

- **Revocation latency:** removing a user from an allowed group only takes
  effect when their token expires and they re-authenticate. The fastest
  lockout lever is blocking the user in GitLab: it prevents new logins and
  stops token refresh, ending existing sessions at the current token
  lifetime — nothing revokes an already-issued token instantly. This is
  accepted deliberately — do not "fix" it by adding a per-request GitLab API
  membership check without revisiting this ADR.
- Exactly one identity provider per deployment (`github` | `gitlab` | `none`);
  the `login` claim is a single namespace (GitLab OIDC `nickname` maps onto it).
- `allowed_groups` (GitLab group full-paths) uses subtree matching: `acme`
  admits members of `acme/dev` etc. Empty `allowed_groups` is permitted for
  self-hosted instances (instance login is the boundary) but the server
  refuses to start with an empty list when the instance URL is gitlab.com,
  where "authenticated" means anyone on the internet.
