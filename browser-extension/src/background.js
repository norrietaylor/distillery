/**
 * Background Service Worker for the Distillery Browser Extension.
 *
 * Responsibilities:
 * - On startup/install: load options, probe localhost:{port}/mcp with initialize
 *   (1-second timeout). On success use local, on failure fall back to remote URL.
 * - Re-probe local server every 5 minutes and on options change.
 * - Maintain a single MCPClient instance (imported from mcp-client.js).
 * - Expose message handlers for popup/content script communication.
 * - Track connection state and broadcast changes to all extension views.
 * - Handle chrome.runtime.onInstalled to open options page on first install.
 * - Manage offline queue: enqueue failed operations, replay on reconnect.
 */

/* global MCPClient, MCPNetworkError, OfflineQueue, startOAuthFlow, clearAuth, getStoredAuth */

importScripts('mcp-client.js');
importScripts('offline-queue.js');
importScripts('auth.js');

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Re-probe interval in milliseconds (5 minutes). */
const PROBE_INTERVAL_MS = 5 * 60 * 1000;

/** Timeout for probing the local MCP server (milliseconds). */
const LOCAL_PROBE_TIMEOUT_MS = 1000;

/** Default configuration — must match options.js DEFAULTS. */
const DEFAULTS = {
  remoteServerUrl: 'https://distillery-mcp.fly.dev/mcp',
  localMcpPort: 8000,
  autoDetectLocal: true,
  defaultProject: '',
  defaultTags: '',
  githubClientId: '',
};

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

/** Shared MCP client instance. */
let mcpClient = new MCPClient();

/** Shared offline queue instance. */
const offlineQueue = new OfflineQueue();

/** Flag to prevent concurrent replay operations. */
let replayInProgress = false;

/**
 * Current connection state broadcast to popup/content scripts.
 *
 * @type {{
 *   connected: boolean,
 *   serverType: 'local'|'remote'|'unknown',
 *   serverUrl: string|null,
 *   username: string|null,
 *   queuedOperations: number
 * }}
 */
let connectionState = {
  connected: false,
  serverType: 'unknown',
  serverUrl: null,
  username: null,
  queuedOperations: 0,
};

/** Timer handle for periodic re-probe. */
let probeIntervalId = null;

/**
 * Most recently detected feeds from the active tab.
 * Updated whenever a content script sends a "feedsDetected" message.
 *
 * @type {Array<{ url: string, title: string, source_type: 'rss'|'atom'|'github' }>}
 */
let detectedFeeds = [];

// ---------------------------------------------------------------------------
// Options helpers
// ---------------------------------------------------------------------------

/**
 * Load options from chrome.storage.local, merging with defaults.
 *
 * @returns {Promise<object>}
 */
async function loadOptions() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  return { ...DEFAULTS, ...stored };
}

// ---------------------------------------------------------------------------
// Connection lifecycle
// ---------------------------------------------------------------------------

/**
 * Attempt to connect to the local MCP server.
 *
 * Creates a fresh MCPClient with a 1-second AbortController timeout,
 * calls initialize(), and returns true on success.
 *
 * @param {number} port - Port number to probe.
 * @returns {Promise<boolean>}
 */
async function probeLocal(port) {
  const localUrl = `http://localhost:${port}/mcp`;
  const probe = new MCPClient();

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), LOCAL_PROBE_TIMEOUT_MS);

  const originalFetch = globalThis.fetch;
  globalThis.fetch = (url, init = {}) =>
    originalFetch(url, { ...init, signal: controller.signal });

  try {
    await probe.initialize(localUrl);
    return true;
  } catch (_err) {
    return false;
  } finally {
    // Always restore the original fetch, whether the probe succeeded or failed.
    globalThis.fetch = originalFetch;
    clearTimeout(timeoutId);
  }
}

/**
 * Establish a connection to either local or remote server.
 *
 * Algorithm:
 * 1. If autoDetectLocal, probe localhost:{localMcpPort}/mcp (1 s timeout).
 * 2. On probe success: initialize shared client against local URL.
 * 3. On probe failure (or autoDetect disabled): initialize against remoteServerUrl.
 * 4. Load stored auth token for remote connections.
 * 5. Update connectionState and broadcast.
 *
 * @returns {Promise<void>}
 */
async function connect() {
  const options = await loadOptions();

  // Disconnect any existing session first.
  mcpClient.disconnect();

  const authData = await chrome.storage.local.get(['authToken', 'authUsername']);

  let targetUrl = options.remoteServerUrl;
  let targetType = 'remote';

  if (options.autoDetectLocal) {
    const localAvailable = await probeLocal(options.localMcpPort);
    if (localAvailable) {
      targetUrl = `http://localhost:${options.localMcpPort}/mcp`;
      targetType = 'local';
    }
  }

  // For remote connections, apply stored auth token.
  if (targetType === 'remote') {
    mcpClient.setAuthToken(authData.authToken || null);
  } else {
    // Local connections do not require auth.
    mcpClient.setAuthToken(null);
  }

  try {
    await mcpClient.initialize(targetUrl);

    const queueCount = await offlineQueue.getCount();

    connectionState = {
      connected: true,
      serverType: targetType,
      serverUrl: targetUrl,
      username: targetType === 'remote' ? (authData.authUsername || null) : null,
      queuedOperations: queueCount,
    };

    // Replay any queued operations now that we are connected.
    if (queueCount > 0) {
      // Fire-and-forget; replayQueue manages its own state.
      replayQueue();
    }
  } catch (err) {
    console.warn(`[background] Failed to connect to ${targetType} server (${targetUrl}):`, err);

    connectionState = {
      connected: false,
      serverType: 'unknown',
      serverUrl: null,
      username: null,
      queuedOperations: connectionState.queuedOperations,
    };
  }

  broadcastConnectionState();
}

/**
 * Broadcast the current connectionState to all extension views.
 *
 * Uses chrome.runtime.sendMessage; swallows errors from views that are
 * not listening (e.g. popup is closed).
 */
function broadcastConnectionState() {
  chrome.runtime.sendMessage(
    { action: 'connectionStatusChanged', data: connectionState },
    () => {
      // Suppress "Could not establish connection" errors when popup is closed.
      void chrome.runtime.lastError;
    }
  );
}

// ---------------------------------------------------------------------------
// Periodic re-probe
// ---------------------------------------------------------------------------

/**
 * Start the 5-minute periodic probe loop using chrome.alarms API,
 * which survives service worker suspension.
 */
function startPeriodicProbe() {
  chrome.alarms.create('distillery-probe', {
    delayInMinutes: 5,
    periodInMinutes: 5,
  });
}

// ---------------------------------------------------------------------------
// Offline queue: replay and badge management
// ---------------------------------------------------------------------------

/**
 * Replay queued operations in FIFO order.
 *
 * Iterates through the queue, attempting each operation via mcpClient.callTool.
 * Successfully replayed items are removed; failures increment their retryCount.
 * The badge is updated after each attempt.
 *
 * @returns {Promise<void>}
 */
async function replayQueue() {
  if (replayInProgress) return;
  if (!mcpClient.isConnected()) return;

  replayInProgress = true;

  try {
    const items = await offlineQueue.getQueue();

    for (const item of items) {
      try {
        await mcpClient.callTool(item.payload.toolName, item.payload.args || {});
        await offlineQueue.removeItem(item.id);
      } catch (err) {
        if (err.name === 'MCPNetworkError') {
          // Connection lost again — stop replaying.
          await offlineQueue.incrementRetry(item.id);
          break;
        }
        // For auth/rate/protocol errors during replay, increment retry and continue.
        await offlineQueue.incrementRetry(item.id);
      }
    }
  } finally {
    replayInProgress = false;
    await updateQueueBadge();
  }
}

/**
 * Update the extension badge to reflect the current queue count.
 *
 * Shows the count with an orange background when the queue is non-empty;
 * clears the badge when the queue is empty.
 *
 * Also updates connectionState.queuedOperations and broadcasts the change.
 *
 * @returns {Promise<void>}
 */
async function updateQueueBadge() {
  const count = await offlineQueue.getCount();

  connectionState.queuedOperations = count;

  if (count > 0) {
    chrome.action.setBadgeText({ text: String(count) });
    chrome.action.setBadgeBackgroundColor({ color: '#F59E0B' }); // Orange/amber
  } else {
    chrome.action.setBadgeText({ text: '' });
  }

  broadcastConnectionState();
}

// ---------------------------------------------------------------------------
// Context menu integration
// ---------------------------------------------------------------------------

/**
 * Register the context menu item on installation.
 *
 * Creates a "Save to Distillery" context menu that appears on any page.
 */
function registerContextMenu() {
  chrome.contextMenus.create({
    id: 'save-to-distillery',
    title: 'Save to Distillery',
    contexts: ['page'],
  });
}

/**
 * Handle context menu click: extract content and save to Distillery.
 *
 * Flow:
 * 1. Get the active tab and send extractContent message to its content script.
 * 2. Build bookmark content using the extracted data.
 * 3. Call distillery_store via the MCP client.
 * 4. Show success (checkmark badge for 2s) or error (red badge with "!") notification.
 */
async function handleContextMenuClick(info, tab) {
  if (info.menuItemId !== 'save-to-distillery') {
    return;
  }

  // Extract content from the active tab's content script.
  let extractedData;
  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: 'extractContent' });

    if (!response || response.status !== 'ok') {
      const errMsg = (response && response.error) ? response.error : 'Content extraction failed.';
      throw new Error(errMsg);
    }

    extractedData = response.data;
  } catch (err) {
    // Content script may not be injected (e.g. chrome:// pages, extensions).
    // Fall back to basic tab metadata.
    console.warn('[background] Content script unavailable, using tab metadata:', err.message);
    extractedData = {
      title: tab.title || '',
      url: tab.url || '',
      description: '',
      articleText: null,
      selectedText: '',
    };
  }

  // Build bookmark content using helper function (from popup.js pattern).
  const content = buildBookmarkContent(
    extractedData.title,
    extractedData.url,
    extractedData.description,
    extractedData.articleText,
    extractedData.selectedText
  );

  // Load default tags and project from options.
  let defaultTags = '';
  let defaultProject = '';
  let author = '';
  try {
    const stored = await chrome.storage.local.get(['defaultTags', 'defaultProject', 'defaultAuthor']);
    defaultTags = stored.defaultTags || '';
    defaultProject = stored.defaultProject || '';
    author = stored.defaultAuthor || '';
  } catch (_err) {
    // Non-fatal.
  }

  // Parse tags.
  const tags = defaultTags
    ? defaultTags.split(',').map((t) => t.trim()).filter(Boolean)
    : [];

  // Determine author: prefer logged-in username over local author setting.
  let finalAuthor = author || '';
  try {
    const statusResp = await chrome.runtime.sendMessage({ action: 'getConnectionStatus' });
    if (statusResp && statusResp.status === 'ok') {
      const state = statusResp.data;
      if (state.username) {
        finalAuthor = state.username;
      }
    }
  } catch (_err) {
    // Non-fatal.
  }

  // Build the distillery_store args.
  const args = {
    content,
    entry_type: 'bookmark',
    source: 'browser-extension',
    tags,
    metadata: {
      url: extractedData.url || '',
      title: extractedData.title || '',
    },
  };

  if (finalAuthor) {
    args.metadata.author = finalAuthor;
  }

  if (defaultProject) {
    args.project = defaultProject;
  }

  // Call distillery_store and handle response.
  try {
    await mcpClient.callTool('distillery_store', args);
    showContextMenuSuccess();
  } catch (err) {
    if (err.name === 'MCPNetworkError') {
      // Queue the operation for later replay.
      try {
        await offlineQueue.enqueue({
          toolName: 'distillery_store',
          args,
        });
        await updateQueueBadge();
        showContextMenuSuccess(); // Show success since it's queued.
      } catch (queueErr) {
        console.error('[background] Failed to queue context menu save:', queueErr.message);
        showContextMenuError();
      }
    } else {
      console.error('[background] Context menu save failed:', err.message);
      showContextMenuError();
    }
  }
}

/**
 * Show a success notification for context menu save.
 *
 * Sets badge to checkmark "✓" with green background for 2 seconds, then clears.
 * Optionally shows a desktop notification.
 *
 * @returns {Promise<void>}
 */
async function showContextMenuSuccess() {
  chrome.action.setBadgeText({ text: '✓' });
  chrome.action.setBadgeBackgroundColor({ color: '#10B981' }); // Green

  // Optionally show a desktop notification.
  try {
    chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icons/icon-128.png',
      title: 'Saved to Distillery',
      message: 'Page has been saved to your Distillery knowledge base.',
    });
  } catch (_err) {
    // Notifications API may not be available; non-fatal.
  }

  // Clear badge after 2 seconds.
  setTimeout(() => {
    chrome.action.setBadgeText({ text: '' });
  }, 2000);
}

/**
 * Show an error notification for context menu save.
 *
 * Sets badge to "!" with red background.
 *
 * @returns {Promise<void>}
 */
async function showContextMenuError() {
  chrome.action.setBadgeText({ text: '!' });
  chrome.action.setBadgeBackgroundColor({ color: '#EF4444' }); // Red

  // Optionally show a desktop notification.
  try {
    chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icons/icon-128.png',
      title: 'Failed to Save',
      message: 'Could not save page to Distillery. Check your connection and try again.',
    });
  } catch (_err) {
    // Notifications API may not be available; non-fatal.
  }
}

/**
 * Build markdown-formatted content for the bookmark entry.
 *
 * Uses selectedText if present, otherwise falls back to articleText.
 * Truncates to 5000 characters.
 *
 * @param {string} title
 * @param {string} url
 * @param {string} description
 * @param {string|null} articleText
 * @param {string} selectedText
 * @returns {string}
 */
function buildBookmarkContent(title, url, description, articleText, selectedText) {
  const body = selectedText || articleText || description || '';
  const lines = [];

  if (title) {
    lines.push(`# ${title}`, '');
  }
  if (url) {
    lines.push(`**URL:** ${url}`, '');
  }
  if (description) {
    lines.push(`**Description:** ${description}`, '');
  }
  if (body) {
    lines.push('---', '', body);
  }

  const content = lines.join('\n');
  if (content.length <= 5000) {
    return content;
  }
  return content.slice(0, 5000);
}

// ---------------------------------------------------------------------------
// Online event handling (service worker scope)
// ---------------------------------------------------------------------------

self.addEventListener('online', () => {
  // When connectivity is restored, attempt to reconnect and replay.
  connect().then(() => {
    if (connectionState.connected) {
      replayQueue();
    }
  });
});

// ---------------------------------------------------------------------------
// Message handlers
// ---------------------------------------------------------------------------

/**
 * Handle messages from popup and content scripts.
 *
 * Supported request.type (from content scripts):
 *   feedsDetected       — update detectedFeeds and set badge (feed count)
 *
 * Supported actions (request.action from popup/background):
 *   getConnectionStatus  — return current connectionState
 *   getDetectedFeeds    — return current detectedFeeds array
 *   callTool            — proxy a tool call through mcpClient (queues on network error)
 *   getQueueCount       — return offline queue length
 *   reconnect           — force immediate reconnect attempt
 */
chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  // Handle messages from content scripts that use request.type (not request.action).
  if (request.type === 'feedsDetected') {
    const feeds = Array.isArray(request.feeds) ? request.feeds : [];
    detectedFeeds = feeds;

    // Update badge to indicate how many feeds were detected.
    if (feeds.length > 0) {
      chrome.action.setBadgeText({ text: String(feeds.length) });
      chrome.action.setBadgeBackgroundColor({ color: '#6366F1' }); // Indigo — feed indicator
    } else {
      // Preserve any existing queue badge; only clear if queue is empty too.
      offlineQueue.getCount().then((count) => {
        if (count === 0) {
          chrome.action.setBadgeText({ text: '' });
        }
      });
    }

    sendResponse({ status: 'ok' });
    return false;
  }

  switch (request.action) {
    case 'getConnectionStatus':
      sendResponse({ status: 'ok', data: connectionState });
      break;

    case 'reconnect':
      connect().then(() => {
        sendResponse({ status: 'ok', data: connectionState });
      });
      return true; // Keep message channel open for async response.

    case 'callTool': {
      const { toolName, args } = request;
      mcpClient
        .callTool(toolName, args || {})
        .then((result) => {
          sendResponse({ status: 'ok', data: result });
        })
        .catch(async (err) => {
          // If we get a 401, clear auth token and notify popup.
          if (err.name === 'MCPAuthError') {
            handleAuthError();
            sendResponse({ status: 'error', error: err.message, errorType: err.name });
            return;
          }

          // Only queue on network errors — not auth (401), rate limit (429),
          // or validation/protocol errors.
          if (err.name === 'MCPNetworkError') {
            const { id, dropped } = await offlineQueue.enqueue({ toolName, args: args || {} });
            await updateQueueBadge();
            sendResponse({
              status: 'queued',
              queueId: id,
              dropped,
              error: err.message,
              errorType: err.name,
            });
            return;
          }

          sendResponse({ status: 'error', error: err.message, errorType: err.name });
        });
      return true; // Keep message channel open for async response.
    }

    case 'getQueueCount': {
      offlineQueue.getCount().then((count) => {
        sendResponse({ status: 'ok', data: { count } });
      });
      return true;
    }

    case 'OPTIONS_UPDATED':
      // Options changed — reconnect immediately to pick up new settings.
      connect();
      sendResponse({ status: 'ok' });
      break;

    case 'getDetectedFeeds':
      // Return the most recently detected feeds for this tab.
      sendResponse({ status: 'ok', data: detectedFeeds });
      break;

    case 'watchList': {
      // Fetch currently watched sources via distillery_watch action:list.
      mcpClient
        .callTool('distillery_watch', { action: 'list' })
        .then((result) => {
          // The MCP tool returns a text/content response; parse the sources list.
          // result.content is an array of { type: 'text', text: '...' } items.
          let sources = [];
          try {
            if (Array.isArray(result.content)) {
              const textContent = result.content
                .filter((c) => c.type === 'text')
                .map((c) => c.text)
                .join('\n');
              // Attempt to parse JSON-embedded sources from the text response.
              const jsonMatch = textContent.match(/```json\s*([\s\S]*?)```/);
              if (jsonMatch) {
                const parsed = JSON.parse(jsonMatch[1]);
                if (Array.isArray(parsed)) {
                  sources = parsed;
                } else if (parsed && Array.isArray(parsed.sources)) {
                  sources = parsed.sources;
                }
              }
            }
          } catch (_parseErr) {
            // Non-fatal; return empty sources.
          }
          sendResponse({ status: 'ok', data: sources });
        })
        .catch((err) => {
          sendResponse({ status: 'error', error: err.message, errorType: err.name });
        });
      return true; // Keep message channel open for async response.
    }

    case 'watchAdd': {
      // Add a feed source via distillery_watch action:add.
      const { url: watchUrl, source_type: watchSourceType, label: watchLabel } = request;
      mcpClient
        .callTool('distillery_watch', {
          action: 'add',
          url: watchUrl,
          source_type: watchSourceType || 'rss',
          label: watchLabel || watchUrl,
        })
        .then((result) => {
          sendResponse({ status: 'ok', data: result });
        })
        .catch((err) => {
          if (err.name === 'MCPAuthError') {
            handleAuthError();
          }
          sendResponse({ status: 'error', error: err.message, errorType: err.name });
        });
      return true; // Keep message channel open for async response.
    }

    case 'watchRemove': {
      // Remove a feed source via distillery_watch action:remove.
      const { url: removeUrl } = request;
      mcpClient
        .callTool('distillery_watch', { action: 'remove', url: removeUrl })
        .then((result) => {
          sendResponse({ status: 'ok', data: result });
        })
        .catch((err) => {
          if (err.name === 'MCPAuthError') {
            handleAuthError();
          }
          sendResponse({ status: 'error', error: err.message, errorType: err.name });
        });
      return true; // Keep message channel open for async response.
    }

    case 'setAuthToken': {
      const { token, username } = request;
      mcpClient.setAuthToken(token || null);
      // Persist to storage.
      chrome.storage.local.set({ authToken: token || null, authUsername: username || null });
      // Re-establish connection with new token.
      connect();
      sendResponse({ status: 'ok' });
      break;
    }

    case 'startOAuth': {
      // Load options to get clientId and serverUrl, then run the OAuth flow.
      loadOptions().then(async (options) => {
        const clientId = options.githubClientId;
        const serverUrl = options.remoteServerUrl;

        try {
          const { token, username } = await startOAuthFlow(clientId, serverUrl);
          // Apply the token to the active MCP client.
          mcpClient.setAuthToken(token);
          // Update connection state with the new username and reconnect.
          await connect();
          sendResponse({ status: 'ok', username });
        } catch (err) {
          console.error('[background] OAuth flow failed:', err.message);
          sendResponse({ status: 'error', error: err.message, errorType: err.name });
        }
      });
      return true; // Keep message channel open for async response.
    }

    case 'signOut': {
      // Clear stored auth credentials and reconnect (will be unauthenticated).
      clearAuth().then(async () => {
        mcpClient.setAuthToken(null);
        await connect();
        sendResponse({ status: 'ok' });
      });
      return true; // Keep message channel open for async response.
    }

    case 'bookmark': {
      // Save a bookmark to Distillery via the distillery_store MCP tool.
      const {
        title,
        url,
        content,
        tags,
        project,
        author,
        metadata: bookmarkMetadata,
      } = request;

      const args = {
        content: content || '',
        entry_type: 'bookmark',
        source: 'browser-extension',
        tags: Array.isArray(tags) ? tags : [],
        metadata: {
          url: url || '',
          title: title || '',
          ...(bookmarkMetadata || {}),
        },
      };

      if (author) {
        args.metadata.author = author;
      }

      if (project) {
        args.project = project;
      }

      mcpClient
        .callTool('distillery_store', args)
        .then((result) => {
          sendResponse({ status: 'ok', data: result });
        })
        .catch(async (err) => {
          if (err.name === 'MCPAuthError') {
            handleAuthError();
            sendResponse({ status: 'error', error: err.message, errorType: err.name });
            return;
          }

          if (err.name === 'MCPNetworkError') {
            const { id, dropped } = await offlineQueue.enqueue({
              toolName: 'distillery_store',
              args,
            });
            await updateQueueBadge();
            sendResponse({
              status: 'queued',
              queueId: id,
              dropped,
              error: err.message,
              errorType: err.name,
            });
            return;
          }

          sendResponse({ status: 'error', error: err.message, errorType: err.name });
        });
      return true; // Keep message channel open for async response.
    }

    default:
      sendResponse({ status: 'error', error: `Unknown action: ${request.action}` });
  }
});

// ---------------------------------------------------------------------------
// Auth error handling
// ---------------------------------------------------------------------------

/**
 * Clear stored auth credentials and update connection state to disconnected.
 * The popup will display the disconnected state and prompt re-authentication.
 */
async function handleAuthError() {
  await chrome.storage.local.remove(['authToken', 'authUsername']);
  mcpClient.setAuthToken(null);

  connectionState = {
    ...connectionState,
    connected: false,
    username: null,
  };

  broadcastConnectionState();
}

// ---------------------------------------------------------------------------
// Context menu click listener
// ---------------------------------------------------------------------------

chrome.contextMenus.onClicked.addListener(handleContextMenuClick);

// ---------------------------------------------------------------------------
// Tab navigation listener (reset detected feeds on page change)
// ---------------------------------------------------------------------------

/**
 * Clear detected feeds when the active tab navigates to a new URL.
 *
 * The content script will re-run on the new page and send a fresh
 * "feedsDetected" message, which will repopulate detectedFeeds and
 * update the badge accordingly.
 */
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === 'loading' && tab.active) {
    detectedFeeds = [];
    // Clear feed badge — queue badge will be restored by updateQueueBadge if needed.
    offlineQueue.getCount().then((count) => {
      if (count > 0) {
        chrome.action.setBadgeText({ text: String(count) });
        chrome.action.setBadgeBackgroundColor({ color: '#F59E0B' });
      } else {
        chrome.action.setBadgeText({ text: '' });
      }
    });
  }
});

// ---------------------------------------------------------------------------
// Alarm listener (periodic probe)
// ---------------------------------------------------------------------------

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'distillery-probe') {
    connect();
  }
});

// ---------------------------------------------------------------------------
// Storage change listener (react to options edits from options page)
// ---------------------------------------------------------------------------

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;

  const relevantKeys = ['remoteServerUrl', 'localMcpPort', 'autoDetectLocal'];
  const hasRelevantChange = relevantKeys.some((key) => key in changes);
  if (hasRelevantChange) {
    connect();
  }
});

// ---------------------------------------------------------------------------
// Lifecycle events
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    // Open options page on first install so user can configure the remote URL.
    chrome.runtime.openOptionsPage();
  }

  // Register context menu on install/update.
  registerContextMenu();

  // Start the periodic probe alarm.
  startPeriodicProbe();

  // Connect on install/update.
  connect();
});

chrome.runtime.onStartup.addListener(() => {
  startPeriodicProbe();
  connect();
});

// ---------------------------------------------------------------------------
// Initial connection on service worker activation
// ---------------------------------------------------------------------------

// Service workers can be activated without firing onStartup (e.g. when the
// popup opens and the worker was idle). Connect immediately so the first
// getConnectionStatus message has something to return.
// Also initialise the badge to reflect any pending queue items.
updateQueueBadge();
connect();
