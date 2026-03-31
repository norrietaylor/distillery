# Team Setup — Connecting to a Hosted Distillery Instance

This guide explains how to connect your Claude Code installation to a hosted Distillery MCP server and authenticate with your GitHub account.

## Prerequisites

- A hosted Distillery instance running with GitHub OAuth enabled
- Your team operator should provide:
  - The **server URL** (e.g., `https://distillery.myteam.com/mcp`)
  - The **GitHub OAuth App ID** (sometimes optional if auto-registered)
- A GitHub account (used for authentication)
- Claude Code installed locally

## Step 1: Add the Server to Claude Code Settings

The Distillery MCP server is configured in your Claude Code settings file.

### Locate your settings file

The settings file is stored at:
- **macOS/Linux:** `~/.claude/settings.json`
- **Windows:** `%APPDATA%\.claude\settings.json` or `C:\Users\<YourUsername>\.claude\settings.json`

### Add the server configuration

Open `settings.json` in your text editor and add the Distillery server configuration under the `mcpServers` section. If the `mcpServers` section doesn't exist, create it.

**Example configuration:**

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

Replace `https://distillery.myteam.com/mcp` with the actual URL provided by your operator.

### Key settings explained

- **url**: The full URL to the Distillery MCP server endpoint (must include the `/mcp` path)
- **transport**: Must be set to `"http"` for remote connections

## Step 2: Authenticate with GitHub

When you invoke your first Distillery skill (e.g., `/recall`, `/distill`), Claude Code will initiate the GitHub OAuth login flow.

### First-time authentication flow

1. **Browser opens automatically** — Your default web browser will open to GitHub's authorization page
2. **Review permissions** — GitHub will ask you to authorize Claude Code to access your user profile information (read-only). This is used to verify your identity
3. **Click "Authorize"** — After reviewing, click the green "Authorize" button
4. **Browser redirects** — You'll be redirected to a success page. The browser window may close automatically
5. **Token saved** — Claude Code securely stores your OAuth token locally in `~/.claude/auth-tokens.json`

### What permissions are requested?

The GitHub OAuth flow requests only the `user` scope, which allows reading:
- Your GitHub username and public profile
- Your email address (if public on your profile)

**No write access is requested.** Your repositories, organizations, issues, and other GitHub data are never accessed or modified.

### How authentication works (technical detail)

GitHub OAuth is used purely as an **identity gate** — it proves who you are so the MCP server can grant access. It does **not** give the server access to your GitHub account.

The flow is handled by FastMCP's `GitHubProvider` ([source](https://github.com/jlowin/fastmcp/blob/main/src/fastmcp/server/auth/providers/github.py)):

1. Claude Code redirects to GitHub's OAuth authorization endpoint
2. User approves the `user` scope (read-only profile access)
3. GitHub returns an access token to FastMCP via callback
4. FastMCP's `GitHubTokenVerifier` calls `https://api.github.com/user` to verify the token and extract identity claims (`login`, `name`, `email`, `avatar_url`)
5. The token is wrapped in an internal `AccessToken` object — tool handlers can read the caller's identity via FastMCP's `Context` object but never see the raw GitHub token

**What this means in practice:**
- The server knows *who* is calling (GitHub username) but cannot act on their behalf
- No GitHub API calls are made beyond `/user` for identity verification
- Organization membership is **not** queried (would require `read:org` scope)
- The `required_scopes` parameter defaults to `["user"]` and is not extended in the current configuration

### Token expiration and refresh

- **Token lifetime**: GitHub OAuth tokens are valid indefinitely until revoked
- **Automatic refresh**: Claude Code handles token refresh automatically when needed
- **Revocation**: To revoke access at any time, visit https://github.com/settings/applications and disconnect Claude Code from your authorized apps

## Step 3: Verify the Connection Works

After authentication, verify that your connection is working by invoking a simple Distillery skill.

### Test with `/recall`

In any Claude conversation, type:

```
/recall test
```

Or invoke the recall skill with any simple search term:

```
/recall hello
```

### Expected behavior

- The skill should complete within 5 seconds
- You'll see search results (even if empty) from the Distillery knowledge base
- If you see results, the connection is working correctly

### If no results appear

This is normal if the knowledge base is empty. The connection is still working. Try:
1. Using the `/distill` skill to add an entry to the knowledge base
2. Then using `/recall` to search for it

## Troubleshooting

### Issue: "Distillery MCP server not available"

**Cause**: Claude Code cannot reach the server.

**Solutions**:

1. **Check the URL** — Verify the URL in `~/.claude/settings.json` matches what your operator provided
   - Common mistakes: missing `/mcp` path suffix, using `http://` instead of `https://`, typos in the domain

2. **Check network connectivity** — Verify you can reach the server:
   ```bash
   curl -I https://distillery.myteam.com/mcp
   ```
   If successful, you'll see `HTTP 200`, `HTTP 401`, or `HTTP 405`
   (`401` is expected on auth-enabled deployments before you complete login)

3. **Restart Claude Code** — After updating `settings.json`, restart Claude Code or reload MCP servers:
   - In Claude Code, look for "Reload MCP Servers" option in the settings

4. **Check server status** — Ask your operator if the server is running
   ```bash
   # Operator can check with:
   curl -I https://distillery.myteam.com/mcp
   # Expected: HTTP 200, 401, or 405
   ```

### Issue: "Authentication failed" or "GitHub OAuth error"

**Cause**: Token is invalid, expired, or credentials are misconfigured on the server.

**Solutions**:

1. **Revoke and re-authenticate**:
   - Delete `~/.claude/auth-tokens.json`
   - Invoke a Distillery skill again to restart the OAuth flow
   - Complete the browser authorization again

2. **Check server credentials** — Ask your operator to verify:
   - The `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are correctly set in the server environment
   - The GitHub OAuth App is registered and active

3. **GitHub account issues**:
   - Ensure your GitHub account is active (not suspended)
   - If you've changed your GitHub password recently, GitHub may require re-authorization

### Issue: "Connection timeout" or "Server unreachable"

**Cause**: Network issues, DNS resolution problems, or server is down.

**Solutions**:

1. **Test network connectivity**:
   ```bash
   ping distillery.myteam.com
   ```
   If ping fails, check your internet connection

2. **Check DNS resolution**:
   ```bash
   nslookup distillery.myteam.com
   ```
   If this fails, DNS is misconfigured

3. **Try the raw IP address** — If DNS works but connection fails, try accessing by IP:
   ```bash
   curl -I https://<server-ip-address>/mcp
   ```

4. **Check server logs** — Ask your operator to check server logs for errors

### Issue: "Wrong URL" error or connection refused

**Cause**: The URL in `settings.json` is incorrect or pointing to the wrong server.

**Solutions**:

1. **Verify the URL with your operator** — Double-check you have the correct URL
2. **Check for typos** — URLs are case-sensitive for paths, confirm casing matches
3. **Verify the path** — The URL must end with `/mcp`
   - Correct: `https://distillery.myteam.com/mcp`
   - Incorrect: `https://distillery.myteam.com` or `https://distillery.myteam.com/`

### Issue: "Token expired" after using the server for a while

**Cause**: OAuth token needs refresh, or the server revoked the token.

**Solutions**:

1. **Revoke and re-authenticate**:
   - Delete `~/.claude/auth-tokens.json`
   - Invoke a Distillery skill again to restart the OAuth flow

2. **Check token validity** — If you're uncomfortable deleting the token file:
   - The token will be automatically refreshed the next time you use a Distillery skill
   - No action needed on your part

## Next Steps

Once connected, you can:

- **Search knowledge** — Use `/recall <query>` to search the team knowledge base
- **Add knowledge** — Use `/distill <topic>` to save notes and discoveries
- **Bookmark entries** — Use `/bookmark` to mark important knowledge for later
- **Check deduplication** — Use `/pour` to review similar entries

For detailed information on each skill, see the skill documentation in your Claude Code MCP browser or consult your operator.

## Getting Help

If you encounter issues not covered here:

1. Check this guide again for your specific symptom
2. Ask your team operator for help
3. Check the server logs with your operator to diagnose server-side issues

## Security Notes

- Your OAuth token is stored locally and never shared with Distillery
- Distillery only receives read-only user profile information from GitHub
- All data you store in Distillery is stored on your team's deployment
- To revoke access, visit https://github.com/settings/applications
