/**
 * MCP Streamable-HTTP Client for the Distillery Browser Extension.
 *
 * Implements a minimal MCP client that communicates with the Distillery MCP
 * server via JSON-RPC 2.0 over HTTP with SSE response parsing.
 *
 * Exports: MCPClient class
 */

/* exported MCPClient */

/**
 * Custom error types for MCP client operations.
 */
class MCPNetworkError extends Error {
  constructor(message, cause) {
    super(message);
    this.name = 'MCPNetworkError';
    this.cause = cause;
  }
}

class MCPAuthError extends Error {
  constructor(message) {
    super(message);
    this.name = 'MCPAuthError';
  }
}

class MCPRateLimitError extends Error {
  constructor(message, retryAfter) {
    super(message);
    this.name = 'MCPRateLimitError';
    this.retryAfter = retryAfter;
  }
}

class MCPProtocolError extends Error {
  constructor(message, code, data) {
    super(message);
    this.name = 'MCPProtocolError';
    this.code = code;
    this.data = data;
  }
}

/**
 * Minimal MCP streamable-HTTP client.
 *
 * Usage:
 *   const client = new MCPClient();
 *   await client.initialize('http://localhost:8000/mcp');
 *   const result = await client.callTool('distillery_store', { content: '...' });
 *   client.disconnect();
 */
class MCPClient {
  constructor() {
    this._serverUrl = null;
    this._sessionId = null;
    this._authToken = null;
    this._requestId = 0;
    this._connected = false;
    this._serverInfo = null;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Initialize a session with the MCP server.
   *
   * Sends a JSON-RPC 2.0 `initialize` request, parses the SSE response,
   * stores the Mcp-Session-Id, and sends the `initialized` notification.
   *
   * @param {string} serverUrl - Full URL to the MCP endpoint (e.g. http://localhost:8000/mcp).
   * @returns {Promise<object>} The server capabilities from the initialize response.
   * @throws {MCPNetworkError} On network failure.
   * @throws {MCPAuthError} On 401 Unauthorized.
   * @throws {MCPRateLimitError} On 429 Too Many Requests.
   */
  async initialize(serverUrl) {
    this._serverUrl = serverUrl;
    this._sessionId = null;
    this._connected = false;
    this._serverInfo = null;

    const initPayload = this._envelope('initialize', {
      protocolVersion: '2025-03-26',
      capabilities: {},
      clientInfo: {
        name: 'distillery-browser-extension',
        version: '0.1.0',
      },
    });

    const response = await this._post(initPayload);

    // Capture Mcp-Session-Id from response headers.
    const sessionId = response.headers.get('Mcp-Session-Id');
    if (sessionId) {
      this._sessionId = sessionId;
    }

    const result = await this._parseResponse(response);

    this._serverInfo = result;
    this._connected = true;

    // Send the `initialized` notification (no id — it is a notification).
    await this._notify('notifications/initialized', {});

    return result;
  }

  /**
   * Call a tool on the MCP server.
   *
   * @param {string} toolName - The tool name to invoke.
   * @param {object} args - Tool arguments.
   * @returns {Promise<object>} The tool result.
   * @throws {MCPNetworkError|MCPAuthError|MCPRateLimitError|MCPProtocolError}
   */
  async callTool(toolName, args) {
    if (!this._connected) {
      throw new MCPProtocolError('Client is not connected. Call initialize() first.', -1);
    }

    const payload = this._envelope('tools/call', {
      name: toolName,
      arguments: args || {},
    });

    const response = await this._post(payload);
    return this._parseResponse(response);
  }

  /**
   * Disconnect from the server and clean up session state.
   */
  disconnect() {
    this._serverUrl = null;
    this._sessionId = null;
    this._connected = false;
    this._serverInfo = null;
    // Intentionally keep _authToken — it persists across sessions.
  }

  /**
   * Set the Bearer token for Authorization headers on remote servers.
   *
   * @param {string|null} token - JWT or access token, or null to clear.
   */
  setAuthToken(token) {
    this._authToken = token || null;
  }

  /**
   * Return the current connection state.
   *
   * @returns {boolean}
   */
  isConnected() {
    return this._connected;
  }

  /**
   * Return server info from the last successful initialize call.
   *
   * @returns {object|null}
   */
  getServerInfo() {
    return this._serverInfo;
  }

  /**
   * Return the current server URL.
   *
   * @returns {string|null}
   */
  getServerUrl() {
    return this._serverUrl;
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  /**
   * Build a JSON-RPC 2.0 request envelope.
   */
  _envelope(method, params) {
    this._requestId += 1;
    return {
      jsonrpc: '2.0',
      id: this._requestId,
      method,
      params: params || {},
    };
  }

  /**
   * Build a JSON-RPC 2.0 notification (no id field).
   */
  _notificationEnvelope(method, params) {
    return {
      jsonrpc: '2.0',
      method,
      params: params || {},
    };
  }

  /**
   * Build request headers.
   */
  _headers() {
    const headers = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    };
    if (this._sessionId) {
      headers['Mcp-Session-Id'] = this._sessionId;
    }
    if (this._authToken) {
      headers['Authorization'] = `Bearer ${this._authToken}`;
    }
    return headers;
  }

  /**
   * Send a POST request to the MCP endpoint.
   *
   * @param {object} body - JSON-RPC payload.
   * @returns {Promise<Response>}
   */
  async _post(body) {
    let response;
    try {
      response = await fetch(this._serverUrl, {
        method: 'POST',
        headers: this._headers(),
        body: JSON.stringify(body),
      });
    } catch (err) {
      this._connected = false;
      throw new MCPNetworkError(`Network request failed: ${err.message}`, err);
    }

    if (response.status === 401) {
      this._connected = false;
      throw new MCPAuthError('Authentication required (401). Re-authenticate with GitHub OAuth.');
    }

    if (response.status === 429) {
      const retryAfter = parseInt(response.headers.get('Retry-After') || '60', 10);
      throw new MCPRateLimitError(
        `Rate limited (429). Retry after ${retryAfter} seconds.`,
        retryAfter
      );
    }

    if (!response.ok) {
      throw new MCPProtocolError(
        `Server returned HTTP ${response.status}: ${response.statusText}`,
        response.status
      );
    }

    return response;
  }

  /**
   * Send a JSON-RPC 2.0 notification (fire-and-forget, no response expected).
   */
  async _notify(method, params) {
    const payload = this._notificationEnvelope(method, params);
    try {
      await fetch(this._serverUrl, {
        method: 'POST',
        headers: this._headers(),
        body: JSON.stringify(payload),
      });
    } catch (_) {
      // Notifications are fire-and-forget — swallow network errors.
    }
  }

  /**
   * Parse the response body. Handles both SSE (text/event-stream) and plain
   * JSON responses.
   *
   * For SSE responses, extracts JSON from `data:` lines and returns the
   * result from the first JSON-RPC response found.
   *
   * @param {Response} response - Fetch Response object.
   * @returns {Promise<object>} Parsed result.
   */
  async _parseResponse(response) {
    const contentType = response.headers.get('Content-Type') || '';

    if (contentType.includes('text/event-stream')) {
      return this._parseSSE(response);
    }

    // Plain JSON response.
    const json = await response.json();
    if (json.error) {
      throw new MCPProtocolError(
        json.error.message || 'Unknown JSON-RPC error',
        json.error.code,
        json.error.data
      );
    }
    return json.result;
  }

  /**
   * Parse an SSE response body.
   *
   * Reads the full text, splits by lines, and extracts JSON from `data:` lines.
   * Returns the result from the first JSON-RPC response found.
   *
   * @param {Response} response
   * @returns {Promise<object>}
   */
  async _parseSSE(response) {
    const text = await response.text();
    const lines = text.split('\n');
    let lastResult = null;

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) {
        continue;
      }

      const dataStr = trimmed.slice(5).trim();
      if (!dataStr || dataStr === '[DONE]') {
        continue;
      }

      let parsed;
      try {
        parsed = JSON.parse(dataStr);
      } catch (_) {
        continue;
      }

      if (parsed.error) {
        throw new MCPProtocolError(
          parsed.error.message || 'Unknown JSON-RPC error',
          parsed.error.code,
          parsed.error.data
        );
      }

      if (parsed.result !== undefined) {
        lastResult = parsed.result;
      }
    }

    if (lastResult === null) {
      throw new MCPProtocolError('No valid JSON-RPC result found in SSE response', -1);
    }

    return lastResult;
  }
}

// Make error classes accessible for instanceof checks by consumers.
if (typeof globalThis !== 'undefined') {
  globalThis.MCPClient = MCPClient;
  globalThis.MCPNetworkError = MCPNetworkError;
  globalThis.MCPAuthError = MCPAuthError;
  globalThis.MCPRateLimitError = MCPRateLimitError;
  globalThis.MCPProtocolError = MCPProtocolError;
}
