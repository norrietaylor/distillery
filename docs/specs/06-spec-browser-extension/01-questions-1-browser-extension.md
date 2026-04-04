# Clarifying Questions — Round 1

## Q1: Local Mode
**Q:** How should the extension connect to a local MCP server?
**A:** Auto-detect — try localhost first, fall back to configured remote URL. Probe localhost:8000/mcp on startup.

## Q2: Browser Support
**Q:** Which browsers to target?
**A:** Chrome and Safari from the start.

## Q3: Content Extraction
**Q:** Use Readability.js for rich bookmark content?
**A:** Yes — include Readability.js for full article text extraction.

## Q4: Offline Queue
**Q:** Queue bookmarks when offline?
**A:** Yes — queue in storage, sync on reconnect.
