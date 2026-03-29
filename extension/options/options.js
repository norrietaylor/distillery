/**
 * Distillery extension options page
 */

const $ = (id) => document.getElementById(id);

const serverUrlInput     = $("server-url");
const tokenInput         = $("token");
const defaultProjectInput= $("default-project");
const autoModeSelect     = $("auto-mode");
const watchedDomainsArea = $("watched-domains");
const fieldWatchedDomains= $("field-watched-domains");
const btnSave            = $("btn-save");
const btnTest            = $("btn-test");
const savedMsg           = $("saved-msg");
const connDot            = $("conn-dot");
const connStatus         = $("conn-status");

// ── Load saved settings ────────────────────────────────────────────────────────

/**
 * Validate gateway URL to ensure it's HTTPS and not a private/local address
 */
function validateGatewayUrl(urlString) {
  try {
    const url = new URL(urlString);

    // Must be HTTPS
    if (url.protocol !== "https:") {
      return { valid: false, error: "Gateway URL must use HTTPS" };
    }

    // Reject localhost and private IPs
    const hostname = url.hostname.toLowerCase();
    if (
      hostname === "localhost" ||
      hostname === "127.0.0.1" ||
      hostname === "::1" ||
      hostname.startsWith("192.168.") ||
      hostname.startsWith("10.") ||
      /^172\.(1[6-9]|2[0-9]|3[0-1])\./.test(hostname)
    ) {
      return { valid: false, error: "Gateway URL cannot be localhost or private IP" };
    }

    return { valid: true };
  } catch (err) {
    return { valid: false, error: "Invalid URL format" };
  }
}

async function load() {
  const stored = await chrome.storage.local.get({
    serverUrl: "",
    token: "",
    project: "",
    autoMode: "manual",
    watchedDomains: "",
  });

  serverUrlInput.value       = stored.serverUrl;
  tokenInput.value           = stored.token;
  defaultProjectInput.value  = stored.project;
  autoModeSelect.value       = stored.autoMode;
  watchedDomainsArea.value   = stored.watchedDomains;

  updateWatchedDomainsVisibility();
}

// ── Save ───────────────────────────────────────────────────────────────────────

btnSave.addEventListener("click", async () => {
  const url = serverUrlInput.value.trim().replace(/\/$/, "");

  // Validate URL before saving
  if (url) {
    const validation = validateGatewayUrl(url);
    if (!validation.valid) {
      setConnStatus("error", validation.error);
      return;
    }
  }

  await chrome.storage.local.set({
    serverUrl:      url,
    token:          tokenInput.value.trim(),
    project:        defaultProjectInput.value.trim(),
    autoMode:       autoModeSelect.value,
    watchedDomains: watchedDomainsArea.value.trim(),
  });

  savedMsg.classList.add("visible");
  setTimeout(() => savedMsg.classList.remove("visible"), 2000);
});

// ── Test connection ────────────────────────────────────────────────────────────

btnTest.addEventListener("click", async () => {
  const url   = serverUrlInput.value.trim().replace(/\/$/, "");
  const token = tokenInput.value.trim();

  if (!url || !token) {
    setConnStatus("error", "Enter server URL and token first");
    return;
  }

  // Validate URL before testing
  const validation = validateGatewayUrl(url);
  if (!validation.valid) {
    setConnStatus("error", validation.error);
    return;
  }

  setConnStatus("unknown", "Testing…");

  try {
    const response = await fetch(`${url}/api/health`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(8000),
    });
    const body = await response.json().catch(() => ({}));

    if (response.ok) {
      const summ = body.summarization ? "summarization enabled" : "⚠ no Anthropic key — summarization disabled";
      setConnStatus("ok", `Connected (v${body.version ?? "?"}) — ${summ}`);
    } else {
      setConnStatus("error", `HTTP ${response.status}: ${body.detail ?? "error"}`);
    }
  } catch (err) {
    setConnStatus("error", `Unreachable: ${err.message}`);
  }
});

function setConnStatus(state, text) {
  connDot.className = `dot dot--${state}`;
  connStatus.textContent = text;
}

// ── Show/hide watched domains field ────────────────────────────────────────────

autoModeSelect.addEventListener("change", updateWatchedDomainsVisibility);

function updateWatchedDomainsVisibility() {
  const show = autoModeSelect.value === "watched-domains";
  fieldWatchedDomains.style.display = show ? "flex" : "none";
}

// ── Boot ──────────────────────────────────────────────────────────────────────

load();
