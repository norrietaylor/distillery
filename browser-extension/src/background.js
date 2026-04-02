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
 */

/* global MCPClient, MCPNetworkError */

importScripts('mcp-client.js');

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

  try {
    // Monkey-patch fetch for this probe to honour the AbortSignal.
    // MCPClient uses the global fetch; we temporarily replace it.
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (url, init = {}) =>
      originalFetch(url, { ...init, signal: controller.signal });

    await probe.initialize(localUrl);

    globalThis.fetch = originalFetch;
    clearTimeout(timeoutId);
    return true;
  } catch (_err) {
    clearTimeout(timeoutId);
    // Restore fetch in case we swapped it before the error.
    return false;
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

    connectionState = {
      connected: true,
      serverType: targetType,
      serverUrl: targetUrl,
      username: targetType === 'remote' ? (authData.authUsername || null) : null,
      queuedOperations: connectionState.queuedOperations,
    };
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
// Message handlers
// ---------------------------------------------------------------------------

/**
 * Handle messages from popup and content scripts.
 *
 * Supported actions:
 *   getConnectionStatus  — return current connectionState
 *   callTool            — proxy a tool call through mcpClient
 *   reconnect           — force immediate reconnect attempt
 */
chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
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
        .catch((err) => {
          // If we get a 401, clear auth token and notify popup.
          if (err.name === 'MCPAuthError') {
            handleAuthError();
          }
          sendResponse({ status: 'error', error: err.message, errorType: err.name });
        });
      return true; // Keep message channel open for async response.
    }

    case 'OPTIONS_UPDATED':
      // Options changed — reconnect immediately to pick up new settings.
      connect();
      sendResponse({ status: 'ok' });
      break;

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
connect();
