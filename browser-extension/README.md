# Distillery Browser Extension

A browser extension for Chrome and Safari that brings Distillery's `/bookmark` and `/watch` capabilities directly into the browser. Save pages and subscribe to feeds with one click.

## Features

- **One-click bookmarking**: Save any web page into your Distillery knowledge base from the browser toolbar
- **Feed subscription**: Automatically detect and subscribe to RSS/Atom feeds and GitHub repositories
- **Auto-detect local servers**: Seamless connection to local Distillery instances (`localhost:8000`)
- **Rich content extraction**: Full article text extraction via Readability.js for high-quality bookmarks
- **Offline resilience**: Queue operations when offline and sync automatically when reconnected
- **GitHub OAuth**: Authenticate with GitHub for remote server access

## Installation

### Chrome (Manifest V3)

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable "Developer mode" (toggle in the top-right corner)
3. Click "Load unpacked"
4. Navigate to and select the `browser-extension/` directory
5. The extension should appear in your toolbar

### Safari (Web Extension)

Safari Web Extension support requires an Xcode project wrapper. Use the `safari-web-extension-converter` tool:

```bash
xcrun safari-web-extension-converter /path/to/browser-extension/
```

This generates an Xcode project. Open it in Xcode, review the generated `Info.plist` mapping, and build to generate the `.app` bundle for installation.

## Configuration

1. Click the Distillery extension icon in the toolbar
2. Click "⚙ Settings" to open the options page
3. Configure:
   - **Remote MCP Server URL**: Default `https://distillery-mcp.fly.dev/mcp` (for remote servers)
   - **Local MCP Port**: Default `8000` (for local development)
   - **Auto-detect local server**: Enable/disable automatic localhost detection
   - **Default project name**: Pre-fill the project field in bookmarks
   - **Default tags**: Comma-separated tags (e.g., `research, browser-saved`)
   - **GitHub OAuth Client ID**: For remote server authentication (optional)

## Usage

### Bookmarking a Page

1. Navigate to any web page
2. Click the Distillery extension icon
3. Click the "Bookmark" tab
4. Review/edit the title, description, and tags
5. Click "Save" to add the page to your knowledge base

Alternatively, right-click on the page and select "Save to Distillery" from the context menu.

### Subscribing to Feeds

1. Navigate to a page with RSS/Atom feeds or a GitHub repository
2. Click the Distillery extension icon
3. The "Watch" tab shows detected feeds
4. Click "Watch" next to any feed to subscribe
5. Manage your subscriptions in the "Watch" tab

### Offline Mode

When offline:
- Bookmark and watch operations queue automatically
- The extension shows a "⚠ {N} pending" indicator
- When connectivity returns, queued operations sync automatically
- You can view pending items in the popup

### Authentication

**For local servers**: No authentication required. The extension connects directly to `localhost:8000/mcp`.

**For remote servers**: 
1. In the popup, click "Sign in with GitHub"
2. Authorize the GitHub OAuth application
3. The extension stores the token securely in browser storage
4. Your username appears in the popup header
5. Click "Sign out" to disconnect

## Development

### Directory Structure

```
browser-extension/
├── manifest.json          # Manifest V3 configuration
├── src/
│   ├── background.js      # Service worker (connection management)
│   ├── content.js         # Content script (page extraction)
│   ├── mcp-client.js      # MCP HTTP client
│   ├── auth.js            # GitHub OAuth flow
│   ├── popup.html         # Popup UI shell
│   ├── popup.js           # Popup UI logic
│   ├── options.html       # Settings page
│   └── options.js         # Settings logic
├── icons/
│   ├── icon-16.png        # Toolbar icon (16×16)
│   ├── icon-48.png        # Toolbar icon (48×48)
│   └── icon-128.png       # Toolbar icon (128×128)
├── vendor/
│   └── readability.js     # Mozilla's Readability library (Apache 2.0 license)
├── safari/                # Safari Xcode project (generated)
└── README.md              # This file
```

### Local Development

1. Clone/checkout the repo and navigate to `browser-extension/`
2. Start a local Distillery instance:
   ```bash
   distillery-mcp --transport http --port 8000
   ```
3. Load the extension in Chrome:
   - Open `chrome://extensions/`
   - Enable Developer mode
   - Click "Load unpacked" and select `browser-extension/`
4. Open a web page and test bookmarking
5. Check stored entries via Claude Code:
   ```bash
   distillery search "page title"
   ```

### Building and Testing

- **Lint/format**: This is a plain JavaScript project with no build step for Chrome. Follow standard WebExtension conventions.
- **Testing**: Use Chrome DevTools to debug:
  - Right-click → Inspect popup to debug `popup.html`
  - Right-click on the page → Inspect content script to debug `content.js`
  - `chrome://extensions/` → Details → "Errors" to view service worker logs
- **Safari**: Build in Xcode and test via the generated `.app` bundle

## Security & Privacy

- OAuth tokens are stored in `chrome.storage.local` (encrypted at rest by the browser)
- The extension never exposes tokens to web pages
- `host_permissions` are scoped to the configured MCP server and `localhost`
- Content extraction respects same-origin: only the DOM of the current page is accessed
- Readability.js runs in a sandboxed content script (isolated from page scripts)

## Non-Goals (v1)

- Firefox support (WebExtension-compatible; can be added later)
- Full MCP SDK (only `initialize` and `tools/call` implemented)
- Server-side changes (works with existing MCP HTTP endpoint)
- Chrome Web Store or Safari App Store listing (side-load only for v1)
- Modifying or deleting existing bookmarks (read-only for now)

## License

Same as Distillery: [LICENSE](../LICENSE)
