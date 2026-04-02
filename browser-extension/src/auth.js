/**
 * GitHub OAuth Authentication Module for the Distillery Browser Extension.
 *
 * Implements GitHub OAuth 2.0 web application flow using
 * chrome.identity.launchWebAuthFlow to handle the browser-extension-specific
 * redirect URI (chrome-extension://{id}/auth-callback.html).
 *
 * Exports (via globalThis for service worker importScripts compatibility):
 *   startOAuthFlow(clientId, serverUrl)  — full OAuth flow; returns {token, username}
 *   getStoredAuth()                      — load {token, username} from storage
 *   clearAuth()                          — sign out; remove token from storage
 *   getUsername()                        — return stored GitHub username or null
 *   isAuthenticated()                    — true if a token is stored
 */

/* exported startOAuthFlow, getStoredAuth, clearAuth, getUsername, isAuthenticated */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** GitHub OAuth authorization endpoint. */
const GITHUB_AUTHORIZE_URL = 'https://github.com/login/oauth/authorize';

/** Scope requested from GitHub. */
const GITHUB_SCOPE = 'user';

/**
 * GitHub user API endpoint — used to fetch the authenticated username
 * after obtaining a token via the server-side token exchange.
 */
const GITHUB_USER_API = 'https://api.github.com/user';

/** Storage keys for persisted auth data. */
const STORAGE_KEY_TOKEN = 'authToken';
const STORAGE_KEY_USERNAME = 'authUsername';

// ---------------------------------------------------------------------------
// Custom error types
// ---------------------------------------------------------------------------

class AuthError extends Error {
  constructor(message) {
    super(message);
    this.name = 'AuthError';
  }
}

class AuthCancelledError extends Error {
  constructor(message) {
    super(message || 'OAuth flow was cancelled by the user.');
    this.name = 'AuthCancelledError';
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Build the GitHub authorization URL for the OAuth flow.
 *
 * @param {string} clientId - GitHub OAuth app client ID.
 * @param {string} redirectUri - Extension callback URI from chrome.identity.
 * @returns {string} Full authorization URL.
 */
function _buildAuthUrl(clientId, redirectUri) {
  const params = new URLSearchParams({
    client_id: clientId,
    scope: GITHUB_SCOPE,
    redirect_uri: redirectUri,
  });
  return `${GITHUB_AUTHORIZE_URL}?${params.toString()}`;
}

/**
 * Extract the authorization code from a redirect URI.
 *
 * After GitHub redirects back to the extension, the URI looks like:
 *   https://{ext-id}.chromiumapp.org/?code=abc123&state=...
 *
 * @param {string} redirectedToUrl - The URL GitHub redirected to.
 * @returns {string} The authorization code.
 * @throws {AuthError} If no code is present in the URL.
 */
function _extractCode(redirectedToUrl) {
  let parsed;
  try {
    parsed = new URL(redirectedToUrl);
  } catch (err) {
    throw new AuthError(`Invalid redirect URL: ${redirectedToUrl}`);
  }

  const code = parsed.searchParams.get('code');
  if (!code) {
    const error = parsed.searchParams.get('error');
    const description = parsed.searchParams.get('error_description');
    throw new AuthError(
      error
        ? `GitHub OAuth error: ${error}${description ? ` — ${description}` : ''}`
        : 'No authorization code in redirect URL'
    );
  }

  return code;
}

/**
 * Exchange an authorization code for an access token via the MCP server.
 *
 * The MCP server's OAuth token endpoint accepts a POST with the code and
 * redirect_uri and returns an access token.
 *
 * Expected request body: { code, redirect_uri }
 * Expected response: { access_token } (or { error, error_description } on failure)
 *
 * @param {string} serverUrl - MCP server base URL (e.g. https://distillery-mcp.fly.dev/mcp).
 * @param {string} code - Authorization code from GitHub.
 * @param {string} redirectUri - The redirect URI used in the initial authorization request.
 * @returns {Promise<string>} The access token.
 * @throws {AuthError} On exchange failure or network error.
 */
async function _exchangeCode(serverUrl, code, redirectUri) {
  // Derive the token endpoint from the MCP server URL.
  // Convention: /mcp → /oauth/token (strips the /mcp suffix).
  const baseUrl = serverUrl.replace(/\/mcp\/?$/, '');
  const tokenUrl = `${baseUrl}/oauth/token`;

  let response;
  try {
    response = await fetch(tokenUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({ code, redirect_uri: redirectUri }),
    });
  } catch (err) {
    throw new AuthError(`Token exchange network error: ${err.message}`);
  }

  let data;
  try {
    data = await response.json();
  } catch (err) {
    throw new AuthError(`Token exchange returned non-JSON response (HTTP ${response.status})`);
  }

  if (!response.ok || data.error) {
    const reason = data.error_description || data.error || `HTTP ${response.status}`;
    throw new AuthError(`Token exchange failed: ${reason}`);
  }

  if (!data.access_token) {
    throw new AuthError('Token exchange response missing access_token field');
  }

  return data.access_token;
}

/**
 * Fetch the GitHub username for a given access token.
 *
 * Uses the GitHub REST API `/user` endpoint. Returns null on failure
 * so that a username resolution error does not abort the whole auth flow.
 *
 * @param {string} token - GitHub access token.
 * @returns {Promise<string|null>} GitHub username or null.
 */
async function _fetchUsername(token) {
  try {
    const response = await fetch(GITHUB_USER_API, {
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    });

    if (!response.ok) {
      return null;
    }

    const data = await response.json();
    return data.login || null;
  } catch (_) {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Run the full GitHub OAuth 2.0 web application flow.
 *
 * Steps:
 * 1. Obtain the extension's redirect URI via chrome.identity.getRedirectURL().
 * 2. Open the GitHub authorization page via chrome.identity.launchWebAuthFlow().
 * 3. Extract the authorization code from the redirect URI.
 * 4. Exchange the code for an access token via the MCP server's token endpoint.
 * 5. Fetch the GitHub username from the GitHub user API.
 * 6. Persist token and username in chrome.storage.local.
 * 7. Return { token, username }.
 *
 * @param {string} clientId - GitHub OAuth app client ID.
 * @param {string} serverUrl - Full MCP server URL used to derive the token endpoint.
 * @returns {Promise<{token: string, username: string|null}>}
 * @throws {AuthCancelledError} If the user cancels or closes the auth popup.
 * @throws {AuthError} On any other error during the OAuth flow.
 */
async function startOAuthFlow(clientId, serverUrl) {
  if (!clientId) {
    throw new AuthError('GitHub client ID is required. Configure it in the extension options.');
  }

  // Step 1: Get the extension redirect URI.
  const redirectUri = chrome.identity.getRedirectURL('github');

  // Step 2: Build the authorization URL and launch the web auth flow.
  const authUrl = _buildAuthUrl(clientId, redirectUri);

  let redirectedToUrl;
  try {
    redirectedToUrl = await new Promise((resolve, reject) => {
      chrome.identity.launchWebAuthFlow(
        { url: authUrl, interactive: true },
        (responseUrl) => {
          if (chrome.runtime.lastError) {
            reject(chrome.runtime.lastError);
          } else if (!responseUrl) {
            reject(new AuthCancelledError());
          } else {
            resolve(responseUrl);
          }
        }
      );
    });
  } catch (err) {
    // chrome.identity.launchWebAuthFlow rejects with a plain Error when the
    // user closes the popup. The message typically contains "cancelled" or
    // "user" on Chrome.
    const message = err && err.message ? err.message.toLowerCase() : '';
    if (
      message.includes('cancel') ||
      message.includes('closed') ||
      message.includes('user') ||
      err instanceof AuthCancelledError
    ) {
      throw new AuthCancelledError();
    }
    throw new AuthError(`OAuth flow failed: ${err && err.message ? err.message : String(err)}`);
  }

  // Step 3: Extract the authorization code from the callback URL.
  const code = _extractCode(redirectedToUrl);

  // Step 4: Exchange the code for an access token.
  const token = await _exchangeCode(serverUrl, code, redirectUri);

  // Step 5: Fetch the GitHub username.
  const username = await _fetchUsername(token);

  // Step 6: Persist token and username.
  await chrome.storage.local.set({
    [STORAGE_KEY_TOKEN]: token,
    [STORAGE_KEY_USERNAME]: username,
  });

  // Step 7: Return auth result.
  return { token, username };
}

/**
 * Retrieve stored auth data from chrome.storage.local.
 *
 * @returns {Promise<{token: string|null, username: string|null}>}
 */
async function getStoredAuth() {
  const stored = await chrome.storage.local.get([STORAGE_KEY_TOKEN, STORAGE_KEY_USERNAME]);
  return {
    token: stored[STORAGE_KEY_TOKEN] || null,
    username: stored[STORAGE_KEY_USERNAME] || null,
  };
}

/**
 * Clear stored auth credentials (sign out).
 *
 * @returns {Promise<void>}
 */
async function clearAuth() {
  await chrome.storage.local.remove([STORAGE_KEY_TOKEN, STORAGE_KEY_USERNAME]);
}

/**
 * Return the stored GitHub username, or null if not authenticated.
 *
 * @returns {Promise<string|null>}
 */
async function getUsername() {
  const stored = await chrome.storage.local.get(STORAGE_KEY_USERNAME);
  return stored[STORAGE_KEY_USERNAME] || null;
}

/**
 * Check whether a valid (non-null) token is stored.
 *
 * Note: This performs a storage read on each call. For hot-path checks,
 * callers should cache the result or use getStoredAuth() directly.
 *
 * @returns {Promise<boolean>}
 */
async function isAuthenticated() {
  const stored = await chrome.storage.local.get(STORAGE_KEY_TOKEN);
  return Boolean(stored[STORAGE_KEY_TOKEN]);
}

// ---------------------------------------------------------------------------
// Module export — make functions available via globalThis for importScripts
// ---------------------------------------------------------------------------

if (typeof globalThis !== 'undefined') {
  globalThis.startOAuthFlow = startOAuthFlow;
  globalThis.getStoredAuth = getStoredAuth;
  globalThis.clearAuth = clearAuth;
  globalThis.getUsername = getUsername;
  globalThis.isAuthenticated = isAuthenticated;
  globalThis.AuthError = AuthError;
  globalThis.AuthCancelledError = AuthCancelledError;
}
