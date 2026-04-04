# Browser Extension E2E (Authenticated)

This folder contains a small Playwright harness to exercise the Distillery browser extension end-to-end (load extension, connect to MCP over HTTP, perform GitHub OAuth once, then run authenticated bookmark + watch actions and verify results via MCP tools).

It is designed for manual execution, not CI.

## Prerequisites

1. Install Playwright and Chromium:

```bash
pip install playwright
playwright install chromium
```

2. You need the demo server’s GitHub OAuth client id so the extension can start the OAuth flow:

```bash
export DEMO_GITHUB_CLIENT_ID="..."
```

Optional:

```bash
export DEMO_REMOTE_MCP_URL="https://distillery-mcp.fly.dev/mcp"
```

## Bootstrap (manual once)

Run this in headed mode so you can complete GitHub login:

```bash
python3 tests/e2e_browser_extension/test_extension_e2e.py --bootstrap-auth
```

The script will:
- Launch Chromium with the unpacked `browser-extension/`.
- Configure extension options to use the remote demo MCP server.
- Click “Sign in with GitHub”.
- Wait until the extension popup shows a non-empty GitHub username.

## Run E2E (authenticated)

After bootstrap, run:

```bash
python3 tests/e2e_browser_extension/test_extension_e2e.py --run
```

The script will:
- Reuse the same persistent Playwright profile so the OAuth token is available (`chrome.storage.local`).
- Navigate to a local deterministic test HTML page.
- Trigger bookmark + watch via the extension background message handlers.
- Verify results by calling MCP HTTP tools using the extension’s stored `authToken`.

## Notes / Expected failure modes

- This harness will currently surface a possible bug where the extension’s bookmark flow may omit the top-level `author` argument required by the MCP tool `distillery_store`.
- Watch is expected to work because `distillery_watch` does not require the same `author` field.

