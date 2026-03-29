# Spec 03 — Browser Extension

## Overview

A Chrome + Safari browser extension that lets users bookmark pages, trigger the `/watch` skill, and interact with a hosted Distillery instance — without requiring a local Claude Code install.

**Key constraints from issue #34:**
- Backend must be hosted (not localhost)
- Fail loudly if no API key / server is configured — no silent fallbacks
- Chrome + Safari (both Manifest V3)
- Self-hosted distribution (not Chrome Web Store / App Store)
- Summarization requires an Anthropic API key; fail if absent

---

## Architecture

```
Browser Extension (Chrome/Safari MV3)
        │
        │  HTTPS POST /api/bookmark  { url, tags, token }
        │  HTTPS POST /api/watch     { url, type, interval, token }
        │  HTTPS GET  /api/status    { token }
        ▼
Hosted HTTP Gateway  (see Spec 04)
        │
        ├─ Auth: token → user config
        ├─ Fetch URL content  (httpx)
        ├─ Summarise  (Claude API — fails if key absent)
        ├─ Dedup check  (distillery_find_similar)
        └─ Store  (distillery_store → DuckDB)
```

The extension never calls Anthropic directly. All intelligence lives in the hosted gateway.

---

## Directory Layout

```
extension/
├── manifest.json                  # Manifest V3 (Chrome + Safari-compatible)
├── background/
│   └── service-worker.js          # Request routing, auth, retry logic
├── popup/
│   ├── popup.html
│   ├── popup.js
│   └── popup.css
├── options/
│   ├── options.html
│   └── options.js
├── content/
│   └── meta-extractor.js          # Extract <title>, <meta description>, keywords
└── icons/
    ├── icon-16.png
    ├── icon-32.png
    ├── icon-48.png
    └── icon-128.png
```

---

## Manifest V3

```json
{
  "manifest_version": 3,
  "name": "Distillery",
  "version": "0.1.0",
  "description": "Save pages to your Distillery knowledge base",
  "permissions": ["activeTab", "contextMenus", "storage"],
  "host_permissions": ["<all_urls>"],
  "background": {
    "service_worker": "background/service-worker.js",
    "type": "module"
  },
  "action": {
    "default_popup": "popup/popup.html",
    "default_icon": { "16": "icons/icon-16.png", "48": "icons/icon-48.png" }
  },
  "options_page": "options/options.html",
  "content_scripts": [
    {
      "matches": ["<all_urls>"],
      "js": ["content/meta-extractor.js"],
      "run_at": "document_idle"
    }
  ]
}
```

**Safari note:** Use `xcrun safari-web-extension-converter extension/` to wrap into a Safari App Extension. No MV3 API differences affect this extension.

---

## Popup UI

### States

| State | Display |
|-------|---------|
| Not configured | "Configure server URL + token in options" with link |
| Server unreachable | Red dot + "Server offline" + retry button |
| Ready | Green dot + current tab URL + tags field + "Bookmark" button |
| Loading | Spinner + "Saving…" |
| Success | Green tick + entry ID + "View in Distillery" link |
| Duplicate | Yellow warning + "Already saved (ID: …)" + "Save anyway" button |
| Error | Red banner with error message (never silently swallows) |

### Tag Input

- Freeform text, space or comma separated
- Prefix `#` is optional (stripped before sending)
- Suggestions pre-populated from page `<meta keywords>` extracted by content script

---

## Options Page

| Setting | Default | Notes |
|---------|---------|-------|
| Server URL | `https://distillery.yourdomain.com` | Required |
| Auth Token | — | Required; stored in `chrome.storage.local` (not sync) |
| Auto-bookmark mode | `manual` | `manual` / `watched-domains` / `all` |
| Watched domains | — | Newline-separated list; triggers on tab close |
| Default project | — | Pre-fills `project` field on all bookmarks |

**No API key field in the extension.** The Anthropic API key lives server-side only.

---

## Context Menu

Right-click on any page or link:
- **"Save to Distillery"** — bookmark current page (same as popup button)
- **"Watch this page"** — register URL for polling (Phase 3, see Spec 05)

---

## Trigger Modes

| Mode | Behaviour |
|------|-----------|
| `manual` | Only when user clicks button or context menu |
| `watched-domains` | Prompt on tab close if domain matches watched list |
| `all` | Silent background bookmark for every page visited |

Default: `manual`.

---

## Error Policy

The extension **never silently swallows errors**. Every failure surfaces to the user:
- No API key on server → `402 Payment Required` → "Server needs an Anthropic API key configured"
- Network error → "Cannot reach server at `<url>`"
- Duplicate found → Yellow warning with existing entry ID (user must confirm to save anyway)
- Server 5xx → Full error message displayed

---

## Safari Distribution

1. Build with `xcrun safari-web-extension-converter extension/ --app-name "Distillery" --bundle-identifier com.distillery.safari`
2. Archive and distribute as a `.dmg` from GitHub Releases
3. Users enable in Safari → Settings → Extensions

---

## Open Questions

- [ ] Should the popup show a "Recent saves" list (last 3)?
- [ ] Should we support bulk-bookmark (multiple selected tabs)?
- [ ] Safari iOS — worth targeting in the same pass?
