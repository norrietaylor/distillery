# Transport Detection — Distillery MCP Setup

Reference material for Steps 1 and 2 of `/setup`.

## Step 1a: MCP Server Detection Logic

Use `ToolSearch` to check whether any `distillery` MCP tools are available. Also read:

- The plugin manifest (`.claude-plugin/plugin.json` in the plugin directory)
- `.mcp.json` in the project root
- `~/.claude.json` (MCP server registrations — project-scoped under `projects[<cwd>].mcpServers` or global `mcpServers`)

Look for any Distillery MCP server entry in these config files to determine if a server is configured.

## State: Needs Authentication

A Distillery MCP server entry exists (in `plugin.json`, `.mcp.json`, or `~/.claude.json`) but `distillery_list(limit=1)` is unavailable or fails (including auth-related failures). This typically means the server is configured with HTTP transport and GitHub OAuth, but the user has not completed the OAuth flow yet.

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

Then skip to Step 6 (Summary) with `MCP Server: needs authentication`.

## Step 2: Transport Classification Table

Classify the transport from the `transport` field already returned by
`distillery_status` in Step 1 — do NOT re-read or parse any config files for this.

| `distillery_status.transport` | Transport | Mode    |
|-------------------------------|-----------|---------|
| `stdio`                       | Local     | `local` |
| `http`                        | Hosted **or** Team HTTP (see below) | `hosted`/`team` |
| `unknown` / missing           | unknown   | —       |

The hosted-vs-team distinction is **cosmetic** and needs the server URL. It is
optional: only resolve it if the URL is available with a single `Read` of one
config file. Do NOT write shell pipelines, `python`/`jq`/`grep` one-liners, or
any JSON-parsing script to extract it — use the `Read` tool, and if the entry
isn't obvious in one read, label it `Hosted/Team HTTP` and move on.

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