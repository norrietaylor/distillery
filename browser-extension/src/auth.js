/**
 * OAuth Authentication Module for the Distillery Browser Extension.
 *
 * Implements MCP OAuth 2.1 flow using the server's own authorization and token
 * endpoints (discovered via RFC 8414 metadata). Uses PKCE (S256) and dynamic
 * client registration per the MCP spec.
 *
 * The server proxies to GitHub OAuth internally — the extension only talks to
 * the MCP server's OAuth endpoints, never to GitHub directly.
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

/** Scope requested. */
const OAUTH_SCOPE = 'user';

/**
 * GitHub user API endpoint — used to fetch the authenticated username
 * after obtaining a token via the server-side token exchange.
 */
const GITHUB_USER_API = 'https://api.github.com/user';

/** Storage keys for persisted auth data. */
const STORAGE_KEY_TOKEN = 'authToken';
const STORAGE_KEY_USERNAME = 'authUsername';
const STORAGE_KEY_CLIENT_ID = 'oauthClientId';
const STORAGE_KEY_CLIENT_SECRET = 'oauthClientSecret';

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
// PKCE helpers
// ---------------------------------------------------------------------------

/**
 * Generate a random code verifier for PKCE (43-128 chars, unreserved charset).
 * @returns {string}
 */
function _generateCodeVerifier() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  return Array.from(array, (b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Derive a S256 code challenge from a code verifier.
 * @param {string} verifier
 * @returns {Promise<string>} Base64url-encoded SHA-256 hash.
 */
async function _deriveCodeChallenge(verifier) {
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  // Base64url encode
  const base64 = btoa(String.fromCharCode(...new Uint8Array(digest)));
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Discover the MCP server's OAuth metadata via RFC 8414.
 *
 * @param {string} serverUrl - Full MCP server URL (e.g. https://distillery-mcp.fly.dev/mcp).
 * @returns {Promise<{authorization_endpoint: string, token_endpoint: string, registration_endpoint: string|null}>}
 */
async function _discoverOAuthMetadata(serverUrl) {
  const baseUrl = serverUrl.replace(/\/mcp\/?$/, '');
  const metadataUrl = `${baseUrl}/.well-known/oauth-authorization-server`;

  try {
    const response = await fetch(metadataUrl, {
      headers: { Accept: 'application/json' },
    });
    if (response.ok) {
      return await response.json();
    }
  } catch (_) {
    // Fall through to defaults.
  }

  // Fallback if discovery fails — use conventional endpoints.
  return {
    authorization_endpoint: `${baseUrl}/authorize`,
    token_endpoint: `${baseUrl}/token`,
    registration_endpoint: `${baseUrl}/register`,
  };
}

/**
 * Dynamically register the extension as an OAuth client with the MCP server.
 *
 * @param {string} registrationEndpoint
 * @param {string} redirectUri
 * @returns {Promise<{client_id: string, client_secret: string|null}>}
 */
async function _registerClient(registrationEndpoint, redirectUri) {
  // Check for cached registration first.
  const cached = await chrome.storage.local.get([STORAGE_KEY_CLIENT_ID, STORAGE_KEY_CLIENT_SECRET]);
  if (cached[STORAGE_KEY_CLIENT_ID]) {
    return {
      client_id: cached[STORAGE_KEY_CLIENT_ID],
      client_secret: cached[STORAGE_KEY_CLIENT_SECRET] || null,
    };
  }

  const response = await fetch(registrationEndpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      client_name: 'Distillery Browser Extension',
      redirect_uris: [redirectUri],
      grant_types: ['authorization_code'],
      response_types: ['code'],
      token_endpoint_auth_method: 'client_secret_post',
    }),
  });

  if (!response.ok) {
    throw new AuthError(`Client registration failed (HTTP ${response.status})`);
  }

  const data = await response.json();
  if (!data.client_id) {
    throw new AuthError('Client registration response missing client_id');
  }

  // Cache registration for future flows.
  await chrome.storage.local.set({
    [STORAGE_KEY_CLIENT_ID]: data.client_id,
    [STORAGE_KEY_CLIENT_SECRET]: data.client_secret || null,
  });

  return {
    client_id: data.client_id,
    client_secret: data.client_secret || null,
  };
}

/**
 * Build the authorization URL using the server's authorize endpoint.
 */
function _buildAuthUrl(authorizationEndpoint, clientId, redirectUri, codeChallenge) {
  const params = new URLSearchParams({
    client_id: clientId,
    response_type: 'code',
    scope: OAUTH_SCOPE,
    redirect_uri: redirectUri,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
  });
  return `${authorizationEndpoint}?${params.toString()}`;
}

/**
 * Extract the authorization code from a redirect URI.
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
        ? `OAuth error: ${error}${description ? ` — ${description}` : ''}`
        : 'No authorization code in redirect URL'
    );
  }

  return code;
}

/**
 * Exchange an authorization code for an access token via the MCP server's token endpoint.
 *
 * @param {string} tokenEndpoint - Server's token endpoint URL.
 * @param {string} code - Authorization code.
 * @param {string} redirectUri - Redirect URI used in auth request.
 * @param {string} clientId - OAuth client ID.
 * @param {string|null} clientSecret - OAuth client secret (if issued).
 * @param {string} codeVerifier - PKCE code verifier.
 * @returns {Promise<string>} The access token.
 */
async function _exchangeCode(tokenEndpoint, code, redirectUri, clientId, clientSecret, codeVerifier) {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri,
    client_id: clientId,
    code_verifier: codeVerifier,
  });
  if (clientSecret) {
    body.set('client_secret', clientSecret);
  }

  let response;
  try {
    response = await fetch(tokenEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        Accept: 'application/json',
      },
      body: body.toString(),
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
 * Run the full MCP OAuth 2.1 flow with PKCE and dynamic client registration.
 *
 * Steps:
 * 1. Discover the server's OAuth metadata (authorization, token, registration endpoints).
 * 2. Dynamically register the extension as an OAuth client (cached after first use).
 * 3. Generate PKCE code verifier + challenge (S256).
 * 4. Open the authorization page via chrome.identity.launchWebAuthFlow().
 * 5. Extract the authorization code from the redirect URI.
 * 6. Exchange the code for an access token with PKCE verifier.
 * 7. Fetch the GitHub username from the GitHub user API.
 * 8. Persist token and username in chrome.storage.local.
 * 9. Return { token, username }.
 *
 * @param {string} _clientId - Ignored (kept for API compat). Client ID is obtained via dynamic registration.
 * @param {string} serverUrl - Full MCP server URL (e.g. https://distillery-mcp.fly.dev/mcp).
 * @returns {Promise<{token: string, username: string|null}>}
 * @throws {AuthCancelledError} If the user cancels or closes the auth popup.
 * @throws {AuthError} On any other error during the OAuth flow.
 */
async function startOAuthFlow(_clientId, serverUrl) {
  if (!serverUrl) {
    throw new AuthError('Server URL is required for OAuth flow.');
  }

  // Step 1: Discover OAuth endpoints.
  const metadata = await _discoverOAuthMetadata(serverUrl);

  // Step 2: Get redirect URI and register the extension as a client.
  const redirectUri = chrome.identity.getRedirectURL('oauth');
  let registration;
  if (metadata.registration_endpoint) {
    registration = await _registerClient(metadata.registration_endpoint, redirectUri);
  } else {
    throw new AuthError('Server does not support dynamic client registration.');
  }

  // Step 3: Generate PKCE code verifier and challenge.
  const codeVerifier = _generateCodeVerifier();
  const codeChallenge = await _deriveCodeChallenge(codeVerifier);

  // Step 4: Build the authorization URL and launch the web auth flow.
  const authUrl = _buildAuthUrl(
    metadata.authorization_endpoint,
    registration.client_id,
    redirectUri,
    codeChallenge
  );

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

  // Step 5: Extract the authorization code from the callback URL.
  const code = _extractCode(redirectedToUrl);

  // Step 6: Exchange the code for an access token with PKCE verifier.
  const token = await _exchangeCode(
    metadata.token_endpoint,
    code,
    redirectUri,
    registration.client_id,
    registration.client_secret,
    codeVerifier
  );

  // Step 7: Fetch the GitHub username.
  const username = await _fetchUsername(token);

  // Step 8: Persist token and username.
  await chrome.storage.local.set({
    [STORAGE_KEY_TOKEN]: token,
    [STORAGE_KEY_USERNAME]: username,
  });

  // Step 9: Return auth result.
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
  await chrome.storage.local.remove([
    STORAGE_KEY_TOKEN,
    STORAGE_KEY_USERNAME,
    STORAGE_KEY_CLIENT_ID,
    STORAGE_KEY_CLIENT_SECRET,
  ]);
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
