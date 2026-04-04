/**
 * Options page logic for Distillery extension
 * Handles loading and saving user configuration to chrome.storage.local
 */

// Default configuration values
const DEFAULTS = {
  remoteServerUrl: 'https://distillery-mcp.fly.dev/mcp',
  localMcpPort: 8000,
  autoDetectLocal: true,
  defaultProject: '',
  defaultTags: '',
  githubClientId: ''
};

/**
 * Load saved options from storage and populate form
 */
async function loadOptions() {
  try {
    const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));

    // Merge stored values with defaults
    const options = { ...DEFAULTS, ...stored };

    // Populate form fields
    document.getElementById('remoteServerUrl').value = options.remoteServerUrl;
    document.getElementById('localMcpPort').value = options.localMcpPort;
    document.getElementById('autoDetectLocal').checked = options.autoDetectLocal;
    document.getElementById('defaultProject').value = options.defaultProject;
    document.getElementById('defaultTags').value = options.defaultTags;
    document.getElementById('githubClientId').value = options.githubClientId;
  } catch (error) {
    console.error('Error loading options:', error);
    showStatus('Error loading settings', 'error');
  }
}

/**
 * Validate form inputs
 */
function validateForm() {
  const url = document.getElementById('remoteServerUrl').value.trim();
  const port = document.getElementById('localMcpPort').value;

  // Validate URL format
  try {
    new URL(url);
  } catch (e) {
    showStatus('Invalid remote server URL', 'error');
    return false;
  }

  // Validate port number
  const portNum = parseInt(port, 10);
  if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
    showStatus('Port must be between 1 and 65535', 'error');
    return false;
  }

  return true;
}

/**
 * Save options to chrome.storage.local
 */
async function saveOptions() {
  if (!validateForm()) {
    return;
  }

  try {
    const options = {
      remoteServerUrl: document.getElementById('remoteServerUrl').value.trim(),
      localMcpPort: parseInt(document.getElementById('localMcpPort').value, 10),
      autoDetectLocal: document.getElementById('autoDetectLocal').checked,
      defaultProject: document.getElementById('defaultProject').value.trim(),
      defaultTags: document.getElementById('defaultTags').value.trim(),
      githubClientId: document.getElementById('githubClientId').value.trim()
    };

    await chrome.storage.local.set(options);
    showStatus('Settings saved successfully', 'success');

    // Notify background service worker of configuration change
    // This allows it to re-detect local server if options changed
    chrome.runtime.sendMessage(
      { type: 'OPTIONS_UPDATED', options },
      (response) => {
        if (chrome.runtime.lastError) {
          console.warn('Background worker not ready:', chrome.runtime.lastError);
        }
      }
    );
  } catch (error) {
    console.error('Error saving options:', error);
    showStatus('Error saving settings', 'error');
  }
}

/**
 * Reset form to default values
 */
async function resetToDefaults() {
  try {
    await chrome.storage.local.set(DEFAULTS);
    await loadOptions();
    showStatus('Settings reset to defaults', 'success');

    // Notify background service worker
    chrome.runtime.sendMessage(
      { type: 'OPTIONS_UPDATED', options: DEFAULTS },
      (response) => {
        if (chrome.runtime.lastError) {
          console.warn('Background worker not ready:', chrome.runtime.lastError);
        }
      }
    );
  } catch (error) {
    console.error('Error resetting options:', error);
    showStatus('Error resetting settings', 'error');
  }
}

/**
 * Display status message to user
 */
function showStatus(message, type = 'info') {
  const statusEl = document.getElementById('status');
  statusEl.textContent = message;
  statusEl.className = `status status-${type}`;
  statusEl.style.display = 'block';

  // Auto-hide success messages after 3 seconds
  if (type === 'success') {
    setTimeout(() => {
      statusEl.style.display = 'none';
    }, 3000);
  }
}

/**
 * Handle form submission
 */
document.getElementById('optionsForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  await saveOptions();
});

/**
 * Handle reset button
 */
document.getElementById('optionsForm').addEventListener('reset', async (e) => {
  e.preventDefault();
  if (confirm('Reset all settings to defaults?')) {
    await resetToDefaults();
  }
});

/**
 * Load options when page opens
 */
document.addEventListener('DOMContentLoaded', loadOptions);
