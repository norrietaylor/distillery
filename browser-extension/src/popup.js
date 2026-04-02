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

      // Re-initialize tabs on switch.
      if (tabName === 'bookmark') {
        initializeBookmarkTab();
      } else if (tabName === 'watch') {
        initializeWatchTab();
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

// ---------------------------------------------------------------------------
// Bookmark Tab
// ---------------------------------------------------------------------------

/**
 * Truncate text to a maximum number of characters.
 *
 * @param {string} text
 * @param {number} maxLen
 * @returns {string}
 */
function truncate(text, maxLen) {
  if (!text || text.length <= maxLen) return text || '';
  return text.slice(0, maxLen);
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

  return truncate(lines.join('\n'), 5000);
}

/**
 * Show the bookmark form in its loading state.
 * Hides form and error; shows spinner.
 */
function showBookmarkLoading() {
  const loading = document.getElementById('bookmark-loading');
  const form = document.getElementById('bookmark-form');
  const error = document.getElementById('bookmark-error');

  loading.style.display = 'flex';
  form.style.display = 'none';
  error.style.display = 'none';
}

/**
 * Show the bookmark form with pre-filled data.
 *
 * @param {Object} data - Extracted content from the content script.
 * @param {string} defaultTags - Default tags from options.
 * @param {string} defaultProject - Default project from options.
 */
function showBookmarkForm(data, defaultTags, defaultProject) {
  const loading = document.getElementById('bookmark-loading');
  const form = document.getElementById('bookmark-form');
  const error = document.getElementById('bookmark-error');

  loading.style.display = 'none';
  error.style.display = 'none';
  form.style.display = 'flex';

  // Reset save feedback
  document.getElementById('save-success').style.display = 'none';
  document.getElementById('save-error').style.display = 'none';

  // Pre-fill fields
  document.getElementById('bookmark-title').value = data.title || '';
  document.getElementById('bookmark-url').value = data.url || '';
  document.getElementById('bookmark-description').value = data.description || '';
  document.getElementById('bookmark-tags').value = defaultTags || '';
  document.getElementById('bookmark-project').value = defaultProject || '';

  // Re-enable save button in case it was disabled from a previous attempt.
  const saveBtn = document.getElementById('bookmark-save-btn');
  saveBtn.disabled = false;
  saveBtn.textContent = 'Save';
}

/**
 * Show an extraction error in the bookmark tab.
 *
 * @param {string} message
 */
function showBookmarkExtractError(message) {
  const loading = document.getElementById('bookmark-loading');
  const form = document.getElementById('bookmark-form');
  const error = document.getElementById('bookmark-error');
  const errorMsg = document.getElementById('bookmark-error-msg');

  loading.style.display = 'none';
  form.style.display = 'none';
  error.style.display = 'block';
  errorMsg.textContent = message || 'Failed to extract page content.';
}

/**
 * Initialize the bookmark tab: query content script and populate form.
 *
 * Called when the Bookmark tab becomes active.
 */
async function initializeBookmarkTab() {
  showBookmarkLoading();

  // Load default tags and project from options storage.
  let defaultTags = '';
  let defaultProject = '';
  try {
    const stored = await chrome.storage.local.get(['defaultTags', 'defaultProject']);
    defaultTags = stored.defaultTags || '';
    defaultProject = stored.defaultProject || '';
  } catch (_err) {
    // Non-fatal — defaults remain empty.
  }

  // Get the active tab and send extractContent message to the content script.
  try {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!activeTab || !activeTab.id) {
      showBookmarkExtractError('No active tab found.');
      return;
    }

    let data;
    try {
      const response = await chrome.tabs.sendMessage(activeTab.id, { type: 'extractContent' });

      if (!response || response.status !== 'ok') {
        const errMsg = (response && response.error) ? response.error : 'Content extraction failed.';
        throw new Error(errMsg);
      }

      data = response.data;
    } catch (contentErr) {
      // Content script may not be injected (e.g. chrome:// pages, extensions).
      // Fall back to basic tab metadata.
      console.warn('[popup] Content script unavailable, using tab metadata:', contentErr.message);
      data = {
        title: activeTab.title || '',
        url: activeTab.url || '',
        description: '',
        articleText: null,
        selectedText: '',
      };
    }

    showBookmarkForm(data, defaultTags, defaultProject);

    // Store extracted data for use by the save handler.
    window._bookmarkExtractedData = data;
  } catch (err) {
    console.error('[popup] Failed to initialize bookmark tab:', err);
    showBookmarkExtractError(err.message || 'Failed to extract page content.');
  }
}

/**
 * Handle the Save button click in the bookmark tab.
 *
 * Sends a "bookmark" message to the background service worker.
 */
async function handleBookmarkSave() {
  const saveBtn = document.getElementById('bookmark-save-btn');
  const saveSuccess = document.getElementById('save-success');
  const saveError = document.getElementById('save-error');
  const saveErrorMsg = document.getElementById('save-error-msg');

  // Collect form values.
  const title = document.getElementById('bookmark-title').value.trim();
  const url = document.getElementById('bookmark-url').value.trim();
  const description = document.getElementById('bookmark-description').value.trim();
  const tagsRaw = document.getElementById('bookmark-tags').value.trim();
  const project = document.getElementById('bookmark-project').value.trim();

  const tags = tagsRaw
    ? tagsRaw.split(',').map((t) => t.trim()).filter(Boolean)
    : [];

  // Get previously extracted data for article text and selection.
  const extracted = window._bookmarkExtractedData || {};

  // Build content (prefer selectedText from extraction).
  const content = buildBookmarkContent(
    title,
    url,
    description,
    extracted.articleText || null,
    extracted.selectedText || ''
  );

  // Determine author from connection state.
  let author = '';
  try {
    const statusResp = await chrome.runtime.sendMessage({ action: 'getConnectionStatus' });
    if (statusResp && statusResp.status === 'ok') {
      const state = statusResp.data;
      if (state.username) {
        author = state.username;
      }
    }
  } catch (_err) {
    // Non-fatal.
  }

  // If no OAuth username, try local author setting.
  if (!author) {
    try {
      const stored = await chrome.storage.local.get('defaultAuthor');
      author = stored.defaultAuthor || '';
    } catch (_err) {
      // Non-fatal.
    }
  }

  // Disable button and show saving state.
  saveBtn.disabled = true;
  saveBtn.textContent = 'Saving...';
  saveSuccess.style.display = 'none';
  saveError.style.display = 'none';

  try {
    const response = await chrome.runtime.sendMessage({
      action: 'bookmark',
      title,
      url,
      content,
      entry_type: 'bookmark',
      source: 'browser-extension',
      tags,
      project: project || null,
      author: author || null,
      metadata: { url, title },
    });

    if (response && response.status === 'ok') {
      saveSuccess.style.display = 'block';
      saveBtn.textContent = 'Saved';
    } else if (response && response.status === 'queued') {
      saveSuccess.style.display = 'block';
      saveBtn.textContent = 'Queued';
    } else {
      const errMsg = (response && response.error) ? response.error : 'Save failed.';
      saveErrorMsg.textContent = errMsg;
      saveError.style.display = 'block';
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
    }
  } catch (err) {
    console.error('[popup] Bookmark save failed:', err);
    saveErrorMsg.textContent = err.message || 'Save failed.';
    saveError.style.display = 'block';
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save';
  }
}

/**
 * Set up the bookmark save button.
 */
function setupBookmarkSaveButton() {
  const saveBtn = document.getElementById('bookmark-save-btn');
  if (saveBtn) {
    saveBtn.addEventListener('click', handleBookmarkSave);
  }
}

// ---------------------------------------------------------------------------
// Watch Tab
// ---------------------------------------------------------------------------

/**
 * Build a DOM element for a detected feed list item.
 *
 * @param {{ url: string, title: string, source_type: string }} feed
 * @returns {HTMLLIElement}
 */
function buildDetectedFeedItem(feed) {
  const li = document.createElement('li');
  li.className = 'watch-list-item';

  const info = document.createElement('div');
  info.className = 'watch-list-item-info';

  const label = document.createElement('span');
  label.className = 'watch-list-item-label';
  label.textContent = feed.title || feed.url;
  label.title = feed.title || feed.url;

  const urlSpan = document.createElement('span');
  urlSpan.className = 'watch-list-item-url';
  urlSpan.textContent = feed.url;
  urlSpan.title = feed.url;

  info.appendChild(label);
  info.appendChild(urlSpan);

  const typeTag = document.createElement('span');
  typeTag.className = `watch-list-item-type type-${feed.source_type}`;
  typeTag.textContent = feed.source_type;

  const watchBtn = document.createElement('button');
  watchBtn.type = 'button';
  watchBtn.className = 'btn btn-watch';
  watchBtn.textContent = 'Watch';
  watchBtn.addEventListener('click', async () => {
    watchBtn.disabled = true;
    watchBtn.textContent = '...';
    try {
      const resp = await chrome.runtime.sendMessage({
        action: 'watchAdd',
        url: feed.url,
        source_type: feed.source_type === 'atom' ? 'rss' : feed.source_type,
        label: feed.title || feed.url,
      });
      if (resp && resp.status === 'ok') {
        watchBtn.textContent = 'Watched';
        // Refresh watched sources list.
        loadWatchedSources();
      } else {
        watchBtn.textContent = 'Watch';
        watchBtn.disabled = false;
        console.error('[popup] watchAdd failed:', resp && resp.error);
      }
    } catch (err) {
      watchBtn.textContent = 'Watch';
      watchBtn.disabled = false;
      console.error('[popup] watchAdd message failed:', err);
    }
  });

  li.appendChild(info);
  li.appendChild(typeTag);
  li.appendChild(watchBtn);
  return li;
}

/**
 * Build a DOM element for a watched source list item.
 *
 * @param {{ url: string, label?: string, source_type?: string }} source
 * @returns {HTMLLIElement}
 */
function buildWatchedSourceItem(source) {
  const li = document.createElement('li');
  li.className = 'watch-list-item';

  const info = document.createElement('div');
  info.className = 'watch-list-item-info';

  const label = document.createElement('span');
  label.className = 'watch-list-item-label';
  label.textContent = source.label || source.url;
  label.title = source.label || source.url;

  const urlSpan = document.createElement('span');
  urlSpan.className = 'watch-list-item-url';
  urlSpan.textContent = source.url;
  urlSpan.title = source.url;

  info.appendChild(label);
  info.appendChild(urlSpan);

  const sourceType = source.source_type || 'rss';
  const typeTag = document.createElement('span');
  typeTag.className = `watch-list-item-type type-${sourceType}`;
  typeTag.textContent = sourceType;

  const unwatchBtn = document.createElement('button');
  unwatchBtn.type = 'button';
  unwatchBtn.className = 'btn btn-unwatch';
  unwatchBtn.textContent = 'Unwatch';
  unwatchBtn.addEventListener('click', async () => {
    unwatchBtn.disabled = true;
    unwatchBtn.textContent = '...';
    try {
      const resp = await chrome.runtime.sendMessage({
        action: 'watchRemove',
        url: source.url,
      });
      if (resp && resp.status === 'ok') {
        li.remove();
        // Check if list is now empty.
        const list = document.getElementById('watched-sources-list');
        if (list && list.children.length === 0) {
          list.style.display = 'none';
          const empty = document.getElementById('watched-sources-empty');
          if (empty) empty.style.display = 'block';
        }
      } else {
        unwatchBtn.textContent = 'Unwatch';
        unwatchBtn.disabled = false;
        console.error('[popup] watchRemove failed:', resp && resp.error);
      }
    } catch (err) {
      unwatchBtn.textContent = 'Unwatch';
      unwatchBtn.disabled = false;
      console.error('[popup] watchRemove message failed:', err);
    }
  });

  li.appendChild(info);
  li.appendChild(typeTag);
  li.appendChild(unwatchBtn);
  return li;
}

/**
 * Populate the Detected Feeds section from the background's detectedFeeds store.
 *
 * @returns {Promise<void>}
 */
async function loadDetectedFeeds() {
  const loadingEl = document.getElementById('detected-feeds-loading');
  const listEl = document.getElementById('detected-feeds-list');
  const emptyEl = document.getElementById('detected-feeds-empty');

  // Show loading.
  loadingEl.style.display = 'flex';
  listEl.style.display = 'none';
  if (emptyEl) emptyEl.style.display = 'none';

  let feeds = [];
  try {
    const resp = await chrome.runtime.sendMessage({ action: 'getDetectedFeeds' });
    if (resp && resp.status === 'ok' && Array.isArray(resp.data)) {
      feeds = resp.data;
    }
  } catch (err) {
    console.error('[popup] getDetectedFeeds failed:', err);
  }

  loadingEl.style.display = 'none';

  if (feeds.length === 0) {
    if (emptyEl) emptyEl.style.display = 'block';
    listEl.style.display = 'none';
  } else {
    listEl.innerHTML = '';
    feeds.forEach((feed) => {
      listEl.appendChild(buildDetectedFeedItem(feed));
    });
    listEl.style.display = 'flex';
    if (emptyEl) emptyEl.style.display = 'none';
  }
}

/**
 * Fetch and display the currently watched sources via distillery_watch action:list.
 *
 * @returns {Promise<void>}
 */
async function loadWatchedSources() {
  const loadingEl = document.getElementById('watched-sources-loading');
  const listEl = document.getElementById('watched-sources-list');
  const emptyEl = document.getElementById('watched-sources-empty');
  const errorEl = document.getElementById('watched-sources-error');

  // Show loading, hide others.
  loadingEl.style.display = 'flex';
  listEl.style.display = 'none';
  if (emptyEl) emptyEl.style.display = 'none';
  if (errorEl) errorEl.style.display = 'none';

  try {
    const resp = await chrome.runtime.sendMessage({ action: 'watchList' });

    loadingEl.style.display = 'none';

    if (!resp || resp.status === 'error') {
      if (errorEl) errorEl.style.display = 'block';
      return;
    }

    const sources = Array.isArray(resp.data) ? resp.data : [];

    if (sources.length === 0) {
      if (emptyEl) emptyEl.style.display = 'block';
      listEl.style.display = 'none';
    } else {
      listEl.innerHTML = '';
      sources.forEach((source) => {
        listEl.appendChild(buildWatchedSourceItem(source));
      });
      listEl.style.display = 'flex';
      if (emptyEl) emptyEl.style.display = 'none';
    }
  } catch (err) {
    console.error('[popup] watchList failed:', err);
    loadingEl.style.display = 'none';
    if (errorEl) errorEl.style.display = 'block';
  }
}

/**
 * Initialize the Watch tab: load detected feeds and watched sources.
 *
 * Called when the Watch tab becomes active.
 *
 * @returns {Promise<void>}
 */
async function initializeWatchTab() {
  await Promise.all([loadDetectedFeeds(), loadWatchedSources()]);
}

/**
 * Set up the Add Feed form in the Watch tab.
 */
function setupWatchAddForm() {
  const addBtn = document.getElementById('watch-add-btn');
  const urlInput = document.getElementById('watch-url-input');
  const typeSelect = document.getElementById('watch-type-select');
  const successEl = document.getElementById('watch-add-success');
  const errorEl = document.getElementById('watch-add-error');
  const errorMsgEl = document.getElementById('watch-add-error-msg');

  if (!addBtn) return;

  addBtn.addEventListener('click', async () => {
    const url = (urlInput ? urlInput.value.trim() : '');
    const sourceType = typeSelect ? typeSelect.value : 'rss';

    // Hide previous feedback.
    if (successEl) successEl.style.display = 'none';
    if (errorEl) errorEl.style.display = 'none';

    if (!url) {
      if (errorMsgEl) errorMsgEl.textContent = 'Please enter a feed URL.';
      if (errorEl) errorEl.style.display = 'block';
      return;
    }

    addBtn.disabled = true;
    addBtn.textContent = 'Adding...';

    try {
      const resp = await chrome.runtime.sendMessage({
        action: 'watchAdd',
        url,
        source_type: sourceType,
        label: url,
      });

      if (resp && resp.status === 'ok') {
        if (urlInput) urlInput.value = '';
        if (successEl) successEl.style.display = 'block';
        // Refresh watched sources.
        loadWatchedSources();
      } else {
        const errMsg = (resp && resp.error) ? resp.error : 'Failed to add feed.';
        if (errorMsgEl) errorMsgEl.textContent = errMsg;
        if (errorEl) errorEl.style.display = 'block';
      }
    } catch (err) {
      console.error('[popup] watchAdd message failed:', err);
      if (errorMsgEl) errorMsgEl.textContent = err.message || 'Failed to add feed.';
      if (errorEl) errorEl.style.display = 'block';
    } finally {
      addBtn.disabled = false;
      addBtn.textContent = 'Watch';
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
  setupBookmarkSaveButton();
  setupWatchAddForm();
  setupAutoRefresh();

  // Initialize bookmark tab immediately since it is the default active tab.
  initializeBookmarkTab();
});
