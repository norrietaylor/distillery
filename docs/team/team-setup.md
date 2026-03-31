# Team Member Guide

Connect your Claude Code installation to a hosted Distillery MCP server and authenticate with your GitHub account.

## Prerequisites

- A hosted Distillery instance running with GitHub OAuth enabled
- The **server URL** from your team operator (e.g., `https://distillery.myteam.com/mcp`)
- A GitHub account
- Claude Code installed locally

## Step 1: Add the Server to Claude Code

Open `~/.claude/settings.json` and add the Distillery server:

```json
{
  "mcpServers": {
    "distillery": {
      "url": "https://distillery.myteam.com/mcp",
      "transport": "http"
    }
  }
}
```

Replace the URL with the one your operator provides.

!!! note "Settings file location"
    - **macOS/Linux:** `~/.claude/settings.json`
    - **Windows:** `%APPDATA%\.claude\settings.json`

## Step 2: Authenticate with GitHub

On first use of any Distillery skill, Claude Code initiates the GitHub OAuth flow:

1. Your browser opens to GitHub's authorization page
2. Review and approve the `user` scope (read-only profile access)
3. Click **"Authorize"**
4. The token is saved locally in `~/.claude/auth-tokens.json`

### What permissions are requested?

Only the `user` scope — your GitHub username and public profile. **No write access** to repositories, organizations, or other GitHub data.

GitHub OAuth is used purely as an **identity gate**: it proves who you are so the MCP server can grant access. The server never gains access to your GitHub account.

### Token lifetime

GitHub OAuth tokens are valid indefinitely until revoked. Claude Code handles refresh automatically. To revoke access, visit [GitHub Authorized Apps](https://github.com/settings/applications).

## Step 3: Verify the Connection

```text
/recall test
```

You should see search results (even if the knowledge base is empty). If the skill completes without errors, the connection is working.

## Troubleshooting

### "Distillery MCP server not available"

1. **Check the URL** — verify `~/.claude/settings.json` matches what your operator provided. The URL must end with `/mcp`
2. **Check connectivity** — `curl -I https://distillery.myteam.com/mcp` should return HTTP 200, 401, or 405
3. **Restart Claude Code** — required after updating `settings.json`
4. **Check server status** — ask your operator if the server is running

### "Authentication failed" or "GitHub OAuth error"

1. Delete `~/.claude/auth-tokens.json` and try again to restart the OAuth flow
2. Ask your operator to verify `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are correctly set
3. Ensure your GitHub account is active and not suspended

### "Connection timeout" or "Server unreachable"

1. Test connectivity: `ping distillery.myteam.com`
2. Check DNS: `nslookup distillery.myteam.com`
3. Ask your operator to check server logs

## Next Steps

- [`/recall`](../skills/recall.md) — search the team knowledge base
- [`/distill`](../skills/distill.md) — capture knowledge from your sessions
- [`/pour`](../skills/pour.md) — synthesize knowledge across multiple entries
- [`/bookmark`](../skills/bookmark.md) — save and annotate URLs

## Security Notes

- Your OAuth token is stored locally and never shared with Distillery
- Distillery only receives read-only user profile information from GitHub
- All data is stored on your team's deployment
- To revoke access: [GitHub Authorized Apps](https://github.com/settings/applications)
