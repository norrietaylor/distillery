# Distillery

A knowledge-base system for Claude Code: stores, searches, and classifies knowledge entries, exposed via an MCP server with skills on top.

## Language

### Authentication

**Identity Provider**:
The external service (GitHub, or a GitLab instance) that proves who a caller is. Exactly one per deployment.
_Avoid_: auth backend, login service

**Identity Gate**:
The yes/no decision of whether an authenticated identity may use this Distillery server at all. Distillery never accesses the provider's resources; authentication is used for identity only.
_Avoid_: permissions, access control (both imply resource-level authorization that does not exist here)

**Allowed Memberships**:
The normalized list of provider-side collectives (GitHub organizations, GitLab groups) that satisfy the Identity Gate. Empty list means instance login alone is sufficient (open-access mode). Spelled `allowed_orgs` for GitHub and `allowed_groups` for GitLab in config.

**GitLab Group**:
A GitLab collective identified by its full path (e.g. `affinitybridge/dev`). Membership arrives in the OIDC `groups` claim at login; no API lookup. An allowed group admits its whole subtree (`acme` admits `acme/dev`).
_Avoid_: org (GitHub-only term), team

**Login**:
The provider-side username carried in the `login` token claim; the single identity namespace for authorship and audit. GitLab's OIDC `nickname` maps onto it.
_Avoid_: user id, handle

**Machine Token**:
A pre-shared bearer token authenticating non-interactive clients (CI). Its own credential: bypasses the OAuth flow and the Identity Gate by design.
