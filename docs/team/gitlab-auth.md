# GitLab Authentication

Deploy the Distillery MCP server in HTTP mode using a GitLab instance — self-hosted or gitlab.com — as the identity provider, instead of GitHub OAuth.

GitLab authentication uses OpenID Connect (OIDC). Like the GitHub provider, it is an **identity gate only**: Distillery requests the `openid profile email` scopes and never accesses your projects, repositories, or other GitLab data.

## Step 1: Register a GitLab OAuth Application

1. On your GitLab instance, go to **Admin Area → Applications** (instance-wide) or **Group → Settings → Applications**. On gitlab.com, use **User Settings → Applications** or a group-owned application.
2. Create a new application:
    - **Name**: `Distillery`
    - **Redirect URI**: `https://distillery.myteam.com/mcp/auth/callback`
    - **Confidential**: yes
    - **Scopes**: `openid`, `profile`, `email`
3. Note the **Application ID** and **Secret**.

!!! warning
    The redirect URI must match exactly. The path is always `/mcp/auth/callback` (managed by FastMCP). HTTPS is required for production.

## Step 2: Environment Variables

```bash
# GitLab OAuth application credentials
export GITLAB_CLIENT_ID="<application-id>"
export GITLAB_CLIENT_SECRET="<secret>"

# Base URL for the OAuth callback (must be publicly accessible)
export DISTILLERY_BASE_URL="https://distillery.myteam.com"
```

## Step 3: Configuration

```yaml
server:
  auth:
    provider: gitlab
    instance_url: https://gitlab.myteam.com   # omit for gitlab.com
    client_id_env: GITLAB_CLIENT_ID
    client_secret_env: GITLAB_CLIENT_SECRET
    allowed_groups:
      - myteam          # GitLab group full-paths
```

**server.auth (GitLab-specific keys)**

| Key | Values | Description |
|-----|--------|-------------|
| `provider` | `gitlab` | Selects GitLab OIDC authentication |
| `instance_url` | URL | Base URL of the GitLab instance. Default `https://gitlab.com` |
| `allowed_groups` | list of group full-paths | Members of any listed group (or its subgroups) may access the server |

### Group access rules

- **Subtree matching**: an allowed group admits its whole subtree — `myteam` admits members of `myteam/dev` and `myteam/dev/platform`, but not `myteam-other`.
- **Self-hosted**: `allowed_groups` may be empty. Anyone who can sign in to your instance may use the server (instance login is the boundary).
- **gitlab.com**: `allowed_groups` **must** be non-empty — the server refuses to start otherwise, because an authenticated gitlab.com user is anyone on the internet.

### Revocation semantics

Group membership is read once, at login, from the OIDC `groups` claim; there are no per-request GitLab API calls. Removing a user from an allowed group takes effect when their token expires and they re-authenticate. The fastest lockout lever is blocking (or deactivating) the user in GitLab: it prevents any new login, and existing sessions end when the current GitLab token lifetime runs out — a blocked user's token can no longer be refreshed. No lever revokes an already-issued token instantly.

## Notes

- Exactly one identity provider per deployment: `github`, `gitlab`, or `none`.
- The GitLab username (`nickname` claim) is used for authorship and audit, the same way the GitHub login is.
- Pre-shared machine tokens (`DISTILLERY_MCP_MACHINE_TOKEN`) work unchanged for CI clients.
- Everything else in [Operator Deployment](deployment.md) (rate limits, webhooks, hosting) applies as-is.
