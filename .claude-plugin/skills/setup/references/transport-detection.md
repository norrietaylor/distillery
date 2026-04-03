# Transport Detection — Distillery MCP Setup

Reference material for Steps 1 and 2 of `/setup`.

## Step 1a: MCP Server Detection Logic

Use `ToolSearch` to check whether any `distillery` MCP tools are available. Also read:

- The plugin manifest (`.claude-plugin/plugin.json` in the plugin directory)
- `.mcp.json` in the project root
- `~/.claude/settings.json`

Look for any Distillery MCP server entry in these config files to determine if a server is configured.

## State: Needs Authentication

A Distillery MCP server entry exists (in `plugin.json`, `.mcp.json`, or `settings.json`) but `distillery_metrics(scope="summary")` is unavailable or returns an auth error. This typically means the server is configured with HTTP transport and GitHub OAuth, but the user has not completed the OAuth flow yet.

Display:

```text
Distillery MCP Server — Authentication Required

The MCP server is configured but needs authentication.
  Server: <URL from config>

To authenticate:
1. Press Ctrl+. (or Cmd+.) to open the MCP server menu
2. Select the Distillery server (it will show "needs authentication")
3. Press Enter — your browser will open for GitHub OAuth
4. Authorize the app in your browser
5. Return here and run /distillery:setup again

Alternatively, you can type: ! claude mcp authenticate distillery
```

Then skip to Step 5 (Summary) with `MCP Server: needs authentication`.

## Step 2: Transport Classification Table

Read the `.mcp.json` file in the project root (or `~/.claude/settings.json` if `.mcp.json` does not exist) to determine the Distillery MCP server configuration.

| URL Pattern | Transport | Mode |
|-------------|-----------|------|
| `localhost`, `127.0.0.1`, or `type: "stdio"` | Local | `local` |
| `distillery-mcp.fly.dev/*` | Hosted | `hosted` |
| Any other remote domain | Team HTTP | `team` |

Display:

```text
Transport: <Local | Hosted | Team HTTP>
URL: <server URL or "stdio">
```
