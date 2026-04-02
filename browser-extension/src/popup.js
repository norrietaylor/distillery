/**
 * Popup UI Controller
 *
 * Displays connection status and manages tab navigation.
 * Queries the background service worker for current connection state.
 */

/**
 * Update the connection status indicator in the header
 * @param {Object} connectionState - State object from background worker
 * @param {boolean} connectionState.connected - Whether connected to server
 * @param {string} connectionState.serverType - 'local' or 'remote'
 * @param {string} [connectionState.serverUrl] - Current server URL
 * @param {string} [connectionState.username] - Authenticated username
 */
function updateConnectionStatus(connectionState) {
  const statusIndicator = document.getElementById('status-indicator');
  const statusLabel = document.getElementById('status-label');
  const serverType = document.getElementById('server-type');
  const statusMessage = document.getElementById('status-message');

  if (connectionState.connected) {
    // Connected state
    statusIndicator.classList.remove('disconnected');
    statusIndicator.classList.add('connected');

    const serverDisplay = connectionState.serverType === 'local'
      ? 'local'
      : (connectionState.serverUrl || 'remote');

    statusLabel.textContent = 'Connected';
    serverType.textContent = `(${serverDisplay})`;

    if (connectionState.username) {
      statusMessage.textContent = `Signed in as ${connectionState.username}`;
    } else if (connectionState.serverType === 'local') {
      statusMessage.textContent = 'Connected to local server';
    } else {
      statusMessage.textContent = 'Connected to remote server';
    }
  } else {
    // Disconnected state
    statusIndicator.classList.remove('connected');
    statusIndicator.classList.add('disconnected');

    statusLabel.textContent = 'Disconnected';
    serverType.textContent = '';
    statusMessage.textContent = 'Cannot reach server. Check settings or try again.';
  }

  // Update offline queue display if present
  updateOfflineQueueDisplay(connectionState);

  // Update auth UI
  updateAuthUI(connectionState);
}

/**
 * Update the auth section based on connection state.
 *
 * Rules:
 *   - local server: hide auth section, show local author name if available
 *   - remote server, authenticated: show auth-user (username + sign-out button)
 *   - remote server, unauthenticated: show sign-in button
 *   - disconnected / unknown: hide auth section
 *
 * @param {Object} connectionState - State object from background worker
 */
function updateAuthUI(connectionState) {
  const authSection = document.getElementById('auth-section');
  const signinBtn = document.getElementById('signin-btn');
  const authUser = document.getElementById('auth-user');
  const authUsername = document.getElementById('auth-username');
  const localAuthor = document.getElementById('local-author');
  const localAuthorLabel = document.getElementById('local-author-label');

  // Hide everything first.
  authSection.style.display = 'none';
  signinBtn.style.display = 'none';
  authUser.style.display = 'none';
  localAuthor.style.display = 'none';

  if (!connectionState.connected) {
    // Disconnected from a remote server — still show the sign-in button so
    // the user can re-authenticate (e.g. after a 401 / token expiry).
    if (connectionState.serverType === 'remote') {
      authSection.style.display = 'block';
      signinBtn.style.display = 'block';
    }
    return;
  }

  if (connectionState.serverType === 'local') {
    // Local connection: show configured author name if present.
    chrome.storage.local.get('defaultAuthor', (stored) => {
      const author = stored.defaultAuthor || null;
      if (author) {
        localAuthorLabel.textContent = `Author: ${author}`;
        localAuthor.style.display = 'block';
      }
    });
    return;
  }

  // Remote connection: show auth UI.
  authSection.style.display = 'block';

  if (connectionState.username) {
    // Authenticated.
    authUsername.textContent = connectionState.username;
    authUser.style.display = 'flex';
    signinBtn.style.display = 'none';
  } else {
    // Unauthenticated.
    signinBtn.style.display = 'block';
    authUser.style.display = 'none';
  }
}

/**
 * Update the offline queue indicator
 * @param {Object} connectionState - State object from background worker
 */
function updateOfflineQueueDisplay(connectionState) {
  const offlineQueue = document.getElementById('offline-queue');
  const queueCount = document.getElementById('queue-count');

  if (connectionState.queuedOperations && connectionState.queuedOperations > 0) {
    queueCount.textContent = connectionState.queuedOperations;
    offlineQueue.style.display = 'block';
  } else {
    offlineQueue.style.display = 'none';
  }
}

/**
 * Initialize popup: fetch connection state and set up event listeners
 */
async function initializePopup() {
  try {
    // Request current connection state from background worker
    const response = await chrome.runtime.sendMessage({
      action: 'getConnectionStatus'
    });

    if (response && response.status === 'ok') {
      updateConnectionStatus(response.data);
    } else {
      // If background worker not ready, show connecting state
      console.log('Background worker not ready, showing default state');
      updateConnectionStatus({
        connected: false,
        serverType: 'unknown'
      });
    }
  } catch (error) {
    // If message fails, show disconnected state
    console.error('Failed to fetch connection status:', error);
    updateConnectionStatus({
      connected: false,
      serverType: 'unknown'
    });
  }
}

/**
 * Set up tab switching functionality
 */
function setupTabNavigation() {
  const tabButtons = document.querySelectorAll('.tab-btn');
  const tabPanels = document.querySelectorAll('.tab-panel');

  tabButtons.forEach(button => {
    button.addEventListener('click', () => {
      // Remove active class from all buttons and panels
      tabButtons.forEach(btn => btn.classList.remove('active'));
      tabPanels.forEach(panel => panel.classList.remove('active'));

      // Add active class to clicked button
      button.classList.add('active');

      // Show corresponding tab panel
      const tabName = button.getAttribute('data-tab');
      const tabPanel = document.getElementById(`${tabName}-tab`);
      if (tabPanel) {
        tabPanel.classList.add('active');
      }
    });
  });
}

/**
 * Set up settings button
 */
function setupSettingsButton() {
  const settingsBtn = document.getElementById('settings-btn');
  settingsBtn.addEventListener('click', () => {
    chrome.runtime.openOptionsPage();
  });
}

/**
 * Set up GitHub OAuth sign-in button.
 *
 * Sends a startOAuth message to the background service worker.
 * The worker calls startOAuthFlow from auth.js, then sends back
 * a connectionStatusChanged broadcast when auth completes.
 */
function setupSignInButton() {
  const signinBtn = document.getElementById('signin-btn');
  signinBtn.addEventListener('click', async () => {
    signinBtn.disabled = true;
    signinBtn.textContent = 'Signing in...';
    try {
      const response = await chrome.runtime.sendMessage({ action: 'startOAuth' });
      if (!response || response.status !== 'ok') {
        const errorMsg = (response && response.error) ? response.error : 'Sign-in failed.';
        console.error('[popup] OAuth failed:', errorMsg);
        signinBtn.textContent = 'Sign in with GitHub';
        signinBtn.disabled = false;
      }
      // On success the background broadcasts connectionStatusChanged,
      // which triggers updateConnectionStatus and refreshes the UI.
    } catch (err) {
      console.error('[popup] startOAuth message failed:', err);
      signinBtn.textContent = 'Sign in with GitHub';
      signinBtn.disabled = false;
    }
  });
}

/**
 * Set up sign-out button.
 *
 * Sends a signOut message to the background service worker.
 * The worker calls clearAuth and re-connects.
 */
function setupSignOutButton() {
  const signoutBtn = document.getElementById('signout-btn');
  signoutBtn.addEventListener('click', async () => {
    try {
      await chrome.runtime.sendMessage({ action: 'signOut' });
      // Background broadcasts connectionStatusChanged after clearing auth.
    } catch (err) {
      console.error('[popup] signOut message failed:', err);
    }
  });
}

/**
 * Set up auto-refresh of connection status
 * Refresh every 5 seconds to detect connection changes
 */
function setupAutoRefresh() {
  // Initial refresh after popup loads
  initializePopup();

  // Refresh every 5 seconds
  setInterval(initializePopup, 5000);

  // Also listen for messages from background worker about connection changes
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'connectionStatusChanged') {
      updateConnectionStatus(request.data);
    }
  });
}

/**
 * Main entry point
 */
document.addEventListener('DOMContentLoaded', () => {
  setupTabNavigation();
  setupSettingsButton();
  setupSignInButton();
  setupSignOutButton();
  setupAutoRefresh();
});
