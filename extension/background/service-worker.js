/**
 * Distillery Browser Extension — Service Worker
 *
 * Responsibilities:
 *  - Receive messages from popup and content script
 *  - POST to the Distillery HTTP Gateway
 *  - Register context menu items
 *  - Handle errors loudly (never silently swallow)
 */

const DEFAULT_SERVER_URL = "https://distillery.yourdomain.com";

// ── Context menu ──────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "distillery-bookmark",
    title: "Save to Distillery",
    contexts: ["page", "link"],
  });
  chrome.contextMenus.create({
    id: "distillery-watch",
    title: "Watch this page",
    contexts: ["page"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = info.linkUrl ?? info.pageUrl;
  if (!url || !tab) return;

  if (info.menuItemId === "distillery-bookmark") {
    const result = await bookmarkUrl(url, [], tab.title ?? "");
    await showNotification(result);
  } else if (info.menuItemId === "distillery-watch") {
    const result = await watchUrl(url);
    await showNotification(result);
  }
});

// ── Message handler (from popup / options) ────────────────────────────────────

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handleMessage(message).then(sendResponse).catch((err) => {
    sendResponse({ ok: false, error: err.message });
  });
  return true; // keep channel open for async response
});

async function handleMessage(message) {
  switch (message.type) {
    case "BOOKMARK":
      return bookmarkUrl(
        message.url,
        message.tags ?? [],
        message.title ?? "",
        message.force ?? false
      );
    case "WATCH":
      return watchUrl(message.url, message.options ?? {});
    case "STATUS":
      return fetchStatus();
    default:
      throw new Error(`Unknown message type: ${message.type}`);
  }
}

// ── API calls ─────────────────────────────────────────────────────────────────

async function getConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get(
      { serverUrl: DEFAULT_SERVER_URL, token: "", project: "" },
      resolve
    );
  });
}

async function bookmarkUrl(url, tags, _title, force = false) {
  const config = await getConfig();
  assertConfigured(config);

  const response = await fetch(`${config.serverUrl}/api/bookmark`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.token}`,
    },
    body: JSON.stringify({
      url,
      tags,
      force,
      project: config.project || undefined,
    }),
  });

  return parseResponse(response);
}

async function watchUrl(url, options = {}) {
  const config = await getConfig();
  assertConfigured(config);

  const response = await fetch(`${config.serverUrl}/api/watch`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.token}`,
    },
    body: JSON.stringify({
      url,
      project: config.project || undefined,
      ...options,
    }),
  });

  return parseResponse(response);
}

async function fetchStatus() {
  const config = await getConfig();
  if (!config.serverUrl || !config.token) {
    return { ok: false, error: "NOT_CONFIGURED" };
  }

  try {
    const response = await fetch(`${config.serverUrl}/api/health`, {
      headers: { Authorization: `Bearer ${config.token}` },
      signal: AbortSignal.timeout(5000),
    });
    const body = await response.json();
    return { ok: response.ok, ...body };
  } catch (err) {
    return { ok: false, error: "UNREACHABLE", message: err.message };
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function assertConfigured(config) {
  if (!config.serverUrl) throw new Error("Server URL not configured. Open extension options.");
  if (!config.token) throw new Error("Auth token not configured. Open extension options.");
}

async function parseResponse(response) {
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(`Server returned non-JSON response (HTTP ${response.status})`);
  }

  if (response.status === 402) {
    throw new Error("Server is missing Anthropic API key. Configure it in gateway.yaml.");
  }
  if (response.status === 409) {
    // Duplicate — return structured result for popup to handle
    return { ok: false, duplicate: true, ...body };
  }
  if (!response.ok) {
    const msg = body?.detail ?? body?.message ?? `HTTP ${response.status}`;
    throw new Error(msg);
  }
  return { ok: true, ...body };
}

async function showNotification(result) {
  const title = result.ok ? "Saved to Distillery" : "Distillery error";
  const message = result.ok
    ? `Saved: ${result.entry_id?.slice(0, 8)}…`
    : result.error ?? "Unknown error";

  chrome.notifications?.create({
    type: "basic",
    iconUrl: "icons/icon-48.png",
    title,
    message,
  });
}
