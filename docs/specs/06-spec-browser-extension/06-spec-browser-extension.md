# 06-spec-browser-extension

## Introduction/Overview

Build a browser extension for Chrome and Safari that brings Distillery's `/bookmark` and `/watch` capabilities directly into the browser. The extension implements a minimal MCP streamable-HTTP client to communicate with the Distillery MCP server (remote or local), uses GitHub OAuth for authentication on remote servers, auto-detects local instances, extracts rich page content via Readability.js, and queues operations when offline. No server-side changes are required.

## Goals

1. One-click bookmarking of any web page into the Distillery knowledge base from the browser toolbar
2. One-click feed subscription when RSS/Atom feeds or GitHub repos are detected on the current page
3. Auto-detect local Distillery instances (`localhost:8000/mcp`) with fallback to a configured remote server
4. Rich content extraction via Readability.js for high-quality bookmark entries
5. Offline resilience — queue operations when the server is unreachable and sync on reconnect

## User Stories

- As a **knowledge worker**, I want to save interesting pages to Distillery without switching to Claude Code so that I capture knowledge in the moment of discovery.
- As a **team member**, I want to subscribe to RSS feeds and GitHub repos I encounter while browsing so that my team's ambient intelligence stays current.
- As a **local user**, I want the extension to auto-detect my local Distillery instance so that I don't need to configure a remote server.
- As a **commuter**, I want bookmarks to queue when I'm offline and sync when I reconnect so that I never lose a capture.

## Demoable Units of Work

### Unit 1: MCP Streamable-HTTP Client and Connection Management

**Purpose:** Establish the core transport layer — a minimal MCP client that connects to the Distillery server (local or remote), handles authentication, and manages sessions.

**Functional Requirements:**
- The extension shall implement an MCP streamable-HTTP client in JavaScript (~200 lines) that supports:
  - `initialize` request (MCP handshake) with `initialized` notification
  - `tools/call` request with JSON-RPC 2.0 envelope
  - SSE response parsing for streamed tool results
  - `Mcp-Session-Id` header management across requests
- The client shall send requests as `POST /mcp` with `Content-Type: application/json` and `Accept: text/event-stream`.
- For remote servers with GitHub OAuth, the client shall include `Authorization: Bearer {JWT}` headers using a token obtained via the OAuth flow (Unit 3).
- For local servers (`localhost`), the client shall connect without OAuth — local Distillery instances default to `auth.provider: "none"`.
- The extension shall auto-detect a local Distillery instance on startup by probing `http://localhost:8000/mcp` with an `initialize` request. If successful, use local; if not, fall back to the configured remote URL.
- The options page shall allow the user to configure:
  - Remote MCP server URL (default: `https://distillery-mcp.fly.dev/mcp`)
  - Local MCP port (default: `8000`)
  - Auto-detect behavior: enabled/disabled
  - Default project name
  - Default tags (comma-separated)
- The extension `manifest.json` shall declare `host_permissions` for both the configured remote URL and `http://localhost:*/*` to bypass CORS restrictions (the MCP server does not set CORS headers).
- The extension shall display connection status in the popup: green indicator for connected (with server type: "local" or "remote"), red for disconnected.
- The client shall handle errors gracefully: network failures → offline queue (Unit 4), 401 → re-trigger OAuth, 429 → respect `Retry-After` header.

**Proof Artifacts:**
- File: `src/mcp-client.js` exists with `initialize()`, `callTool()`, and `disconnect()` methods
- File: `src/options.html` + `src/options.js` exist with server URL, port, and auto-detect configuration
- Test: Extension popup shows green "Connected (local)" when `distillery-mcp --transport http` is running locally
- Test: Extension popup shows green "Connected (remote)" when configured with a remote URL and authenticated

### Unit 2: Bookmark Flow with Readability.js Content Extraction

**Purpose:** Enable one-click bookmarking from the browser with rich content extraction, tag input, and context menu integration.

**Functional Requirements:**
- The extension shall include a content script (`content.js`) that runs on all pages and extracts:
  - `document.title`, `window.location.href`
  - `<meta name="description">` content
  - Open Graph metadata: `og:title`, `og:description`, `og:image`
  - Full article text via Readability.js (Mozilla's readability library, bundled with the extension)
- The extension shall include a popup UI with a "Bookmark" tab showing:
  - Page title (editable)
  - URL (read-only)
  - Extracted description (editable, pre-filled from meta/Readability)
  - Tag input field (comma-separated, with default tags from options pre-filled)
  - Project dropdown (pre-filled from options default)
  - "Save" button
- Clicking "Save" shall call `distillery_store` via the MCP client with:
  - `content`: Markdown-formatted text combining title, description, and Readability-extracted text (truncated to 5,000 chars if necessary)
  - `entry_type`: `"bookmark"`
  - `author`: GitHub username (from OAuth) or configured local author
  - `tags`: user-entered tags
  - `source`: `"browser-extension"`
  - `metadata`: `{"url": "<page-url>", "title": "<page-title>"}`
- The extension shall register a context menu item "Save to Distillery" that triggers the bookmark flow for the current page without opening the popup.
- After a successful save, the extension shall show a brief success notification (badge check mark, 2 seconds) and optionally a desktop notification.
- If the user has selected text on the page, the bookmark content shall use the selected text instead of the Readability-extracted text.

**Proof Artifacts:**
- File: `src/content.js` exists with metadata extraction and Readability integration
- File: `src/popup.html` + `src/popup.js` exist with Bookmark tab UI
- CLI: After bookmarking a page, `distillery search "page title"` returns the stored entry with `entry_type: bookmark`
- Test: Right-click → "Save to Distillery" on any page stores an entry without opening the popup

### Unit 3: GitHub OAuth Flow and Auth Management

**Purpose:** Authenticate users via GitHub OAuth for remote Distillery servers, reusing the same OAuth app as the MCP HTTP deployment.

**Functional Requirements:**
- The extension shall implement GitHub OAuth 2.0 web application flow using `chrome.identity.launchWebAuthFlow` (Chrome) or the equivalent Safari Web Extension API.
- The OAuth flow shall:
  1. Open a popup window to GitHub's authorization URL with `scope=user`
  2. Handle the redirect callback to capture the authorization code
  3. Exchange the code for an access token via the MCP server's OAuth token endpoint
  4. Store the token in `chrome.storage.local` (encrypted at rest by the browser)
- The GitHub OAuth app client ID shall be configurable in the extension options (default: the Distillery demo server's client ID).
- The extension shall display the authenticated GitHub username in the popup header when connected to a remote server.
- The extension shall handle token expiry: on 401 response from the MCP server, clear the stored token and prompt re-authentication.
- For local connections (no OAuth required), the extension shall skip the OAuth flow and use a locally configured author name instead.
- The extension shall provide a "Sign out" button in the popup that clears the stored token and disconnects.

**Proof Artifacts:**
- Test: Clicking "Sign in with GitHub" in the popup opens GitHub authorization page
- Test: After completing OAuth, the popup displays the GitHub username
- Test: After sign-out, the extension shows "Sign in" prompt for remote servers
- Test: Local connections work without OAuth prompt

### Unit 4: Feed Detection, Watch Flow, and Offline Queue

**Purpose:** Detect RSS/Atom/GitHub feeds on pages, offer one-click subscription, and queue all operations when offline for later sync.

**Functional Requirements:**
- The content script shall detect feed sources on the current page:
  - `<link rel="alternate" type="application/rss+xml">` and `type="application/atom+xml"` — extract `href` and `title`
  - GitHub repository pages: match `github.com/{owner}/{repo}` URL patterns — offer to watch as `source_type: "github"`
- When feeds are detected, the extension shall display a badge icon on the toolbar (e.g., RSS icon or counter showing number of feeds found).
- The popup shall include a "Watch" tab showing:
  - Detected feeds on the current page (if any) with "Watch" buttons
  - Manually entered feed URL input with source type selector (RSS / GitHub)
  - List of currently watched sources (fetched via `distillery_watch` with `action: "list"`)
  - "Unwatch" buttons next to each watched source
- Clicking "Watch" shall call `distillery_watch` via the MCP client with `action: "add"`, `url`, `source_type`, and `label`.
- The extension shall maintain an offline queue in `chrome.storage.local`:
  - When an MCP call fails due to network error (not auth or validation errors), the operation shall be queued with its full payload and a timestamp.
  - The queue shall be displayed in the popup with a count badge (e.g., "3 pending").
  - When connectivity is restored (detected via `navigator.onLine` event or successful MCP ping), the extension shall replay queued operations in FIFO order.
  - Successfully replayed operations shall be removed from the queue; failures shall remain with an incremented retry count.
  - The queue shall cap at 100 items. Beyond that, oldest items are dropped with a warning notification.
- The background service worker shall listen for `online` events and trigger queue replay.

**Proof Artifacts:**
- Test: Visiting a page with `<link rel="alternate" type="application/rss+xml">` shows feed badge icon
- Test: Clicking "Watch" on a detected feed, then running `/watch list` in Claude Code shows the new source
- Test: Bookmarking while offline queues the operation; reconnecting syncs it
- Test: Popup shows "3 pending" badge when 3 operations are queued

## Non-Goals (Out of Scope)

- Firefox support (architecture is WebExtension-compatible; Firefox can be added later with minimal changes)
- Full MCP client SDK — only `initialize` and `tools/call` are needed
- Server-side changes — the extension works with the existing MCP HTTP endpoint
- Modifying or deleting existing bookmarks/entries from the extension (read via `/recall` in Claude Code)
- Displaying search results or knowledge base contents in the extension
- Chrome Web Store or Safari App Store listing (side-load for v1)
- Native messaging for stdio transport (local mode uses HTTP)

## Design Considerations

- **Popup UI**: Minimal, two-tab design (Bookmark / Watch). Clean typography, monochrome with accent color matching Distillery branding. Max 400px wide, 500px tall.
- **Badge states**: Default (neutral), feed detected (RSS icon or number), pending sync (orange dot with count), error (red dot).
- **Content extraction**: Readability.js adds ~70KB to the extension bundle. This is acceptable for the content quality improvement.
- **Safari packaging**: Safari Web Extensions require an Xcode project wrapper. The JavaScript source is shared with Chrome; only the packaging and `manifest.json` ↔ `Info.plist` mapping differs. Use `safari-web-extension-converter` CLI tool for initial scaffolding.

## Repository Standards

- Extension source lives in a new top-level directory: `browser-extension/`
- Subdirectories: `src/` (JS/HTML/CSS), `icons/` (toolbar icons), `vendor/` (Readability.js), `safari/` (Xcode wrapper)
- No build step required for Chrome (plain JS, no bundler). Safari requires Xcode build.
- README in `browser-extension/README.md` with installation and development instructions.

## Technical Considerations

- **MCP Streamable-HTTP**: The extension sends `POST /mcp` with JSON-RPC 2.0 payloads. Responses may be SSE streams (`text/event-stream`) — parse `data:` lines for tool results. The `Mcp-Session-Id` header from the `initialize` response must be included in subsequent requests.
- **CORS**: The MCP server has no CORS headers. Extensions bypass CORS via `host_permissions` in `manifest.json`, so `fetch()` calls work without CORS middleware. This applies to both Chrome and Safari.
- **Auto-detect local**: Probe `http://localhost:{port}/mcp` with a lightweight `initialize` request (1-second timeout). On success, use local; on failure, fall back to remote. Re-probe periodically (every 5 minutes) or on options change.
- **Readability.js**: Bundle `@mozilla/readability` (MIT license) in `vendor/`. Run in content script context — it needs DOM access. Extract article after DOMContentLoaded.
- **Safari Web Extensions**: Use the `safari-web-extension-converter` tool to generate the Xcode project from the Chrome extension. The converter handles `manifest.json` → `Info.plist` translation. Both browsers use the same WebExtension APIs (`browser.*` namespace with `chrome.*` polyfill).
- **Storage**: `chrome.storage.local` for OAuth token, options, and offline queue. Storage limit is 10MB (Chrome) / 5MB (Safari) — more than sufficient for queued operations.

## Security Considerations

- OAuth tokens are stored in `chrome.storage.local`, which is encrypted at rest by the browser and isolated to the extension.
- The extension never exposes the OAuth token to web pages — it's used only in background service worker fetch calls.
- `host_permissions` should be scoped to the configured MCP server URL and `localhost`, not `<all_urls>`.
- Readability.js runs in a content script (sandboxed from the page's JS context) — it can read DOM but not execute page scripts.
- The offline queue stores full MCP payloads including content — if the user's machine is compromised, queued bookmarks are readable. This is acceptable given that `chrome.storage.local` is already the trust boundary.
- Content extraction respects same-origin: the content script only reads the DOM of the page the user is actively viewing.

## Success Metrics

| Metric | Target |
|--------|--------|
| Extension installs on Chrome | Manifest v3, loads without errors |
| Extension installs on Safari | Via Xcode project, loads without errors |
| Bookmark round-trip | Page → extension → MCP → retrievable via `/recall` |
| Watch round-trip | Detected feed → extension → MCP → visible via `/watch list` |
| Local auto-detect | Connects to `localhost:8000` when MCP server running locally |
| Offline queue | Queued operations sync on reconnect within 30 seconds |
| Content quality | Readability-extracted bookmarks contain article body, not just title/URL |

## Open Questions

1. **Safari `chrome.identity` equivalent**: Safari Web Extensions support `browser.identity` but the OAuth popup flow may differ in allowed redirect URI schemes. Need to verify during implementation whether `launchWebAuthFlow` works identically or requires Safari-specific handling.
2. **Extension distribution**: Side-load only for v1. Chrome Web Store and Safari App Store listings deferred — requires developer accounts and review processes.
