/**
 * Distillery popup script
 *
 * State machine:
 *   unconfigured → (open options)
 *   ready        → loading → success | error | duplicate
 *   duplicate    → loading (force) | ready (cancel)
 */

// ── DOM refs ─────────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const statusDot      = $("status-dot");
const currentUrl     = $("current-url");
const tagsInput      = $("tags-input");
const btnBookmark    = $("btn-bookmark");
const btnBookmarkTxt = $("btn-bookmark-text");
const btnBookmarkSpin= $("btn-bookmark-spinner");
const btnWatch       = $("btn-watch");
const btnRetry       = $("btn-retry");
const btnOpenOptions = $("btn-open-options");
const btnSaveAnyway  = $("btn-save-anyway");
const btnCancelDup   = $("btn-cancel-dup");
const linkOptions    = $("link-options");

const errorText      = $("error-text");
const dupEntryId     = $("dup-entry-id");
const dupSimilarity  = $("dup-similarity");
const successEntryId = $("success-entry-id");
const successSummary = $("success-summary");

// ── State ────────────────────────────────────────────────────────────────────

let activeTab = null;
let pageMeta  = {};
let lastDuplicatePayload = null;

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  activeTab = tab;

  if (tab?.url) {
    currentUrl.textContent = tab.url;
  }

  // Collect meta from content script
  if (tab?.id) {
    try {
      const response = await chrome.tabs.sendMessage(tab.id, { type: "GET_META" });
      pageMeta = response ?? {};
      if (pageMeta.keywords?.length) {
        tagsInput.placeholder = pageMeta.keywords.slice(0, 3).join(", ");
      }
    } catch {
      // Content script not loaded on this tab (e.g. chrome:// pages)
    }
  }

  // Check server status
  const status = await sendToBackground({ type: "STATUS" });
  applyStatus(status);
}

function applyStatus(status) {
  if (status.error === "NOT_CONFIGURED") {
    showState("unconfigured");
    setDot("unknown");
  } else if (!status.ok) {
    setDot("error");
    // Still allow the form — user might fix connectivity
    showState("ready");
  } else {
    setDot("ok");
    showState("ready");
  }
}

// ── Bookmark ─────────────────────────────────────────────────────────────────

btnBookmark.addEventListener("click", () => doBookmark(false));
btnSaveAnyway.addEventListener("click", () => doBookmark(true));

async function doBookmark(force) {
  if (!activeTab?.url) return;

  const tags = parseTags(tagsInput.value);

  setLoading(true);
  showState("ready");

  const message = { type: "BOOKMARK", url: activeTab.url, tags, force };
  const result = await sendToBackground(message);

  setLoading(false);

  if (result.duplicate && !force) {
    lastDuplicatePayload = result;
    dupEntryId.textContent = result.existing_id?.slice(0, 8) + "…";
    dupSimilarity.textContent = `${Math.round((result.similarity ?? 0) * 100)}%`;
    showState("duplicate");
  } else if (!result.ok) {
    errorText.textContent = result.error ?? "Unexpected error";
    setDot("error");
    showState("error");
  } else {
    successEntryId.textContent = result.entry_id?.slice(0, 8) + "…";
    successSummary.textContent = result.summary ?? "";
    showState("success");
  }
}

// ── Watch ─────────────────────────────────────────────────────────────────────

btnWatch.addEventListener("click", async () => {
  if (!activeTab?.url) return;

  setLoading(true);
  const result = await sendToBackground({ type: "WATCH", url: activeTab.url });
  setLoading(false);

  if (!result.ok) {
    errorText.textContent = result.error ?? "Watch failed";
    showState("error");
  } else {
    successEntryId.textContent = result.watch_id?.slice(0, 8) + "…";
    successSummary.textContent = `Watching every ${result.interval ?? "6h"}`;
    showState("success");
  }
});

// ── Navigation ────────────────────────────────────────────────────────────────

btnRetry.addEventListener("click", init);
btnCancelDup.addEventListener("click", () => showState("ready"));
btnOpenOptions.addEventListener("click", () => chrome.runtime.openOptionsPage());
linkOptions.addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function showState(name) {
  for (const el of document.querySelectorAll(".state")) {
    el.classList.add("hidden");
  }
  const target = $(`state-${name}`);
  if (target) target.classList.remove("hidden");
}

function setDot(state) {
  statusDot.className = `dot dot--${state}`;
  const labels = { ok: "Connected", error: "Error", unknown: "Unknown", degraded: "Degraded" };
  statusDot.title = labels[state] ?? state;
}

function setLoading(loading) {
  btnBookmark.disabled = loading;
  btnWatch.disabled = loading;
  btnBookmarkTxt.classList.toggle("hidden", loading);
  btnBookmarkSpin.classList.toggle("hidden", !loading);
}

function parseTags(raw) {
  return raw
    .split(/[\s,]+/)
    .map((t) => t.replace(/^#/, "").trim().toLowerCase())
    .filter(Boolean);
}

function sendToBackground(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
      } else {
        resolve(response ?? { ok: false, error: "No response" });
      }
    });
  });
}

// ── Boot ──────────────────────────────────────────────────────────────────────

init().catch((err) => {
  errorText.textContent = err.message;
  showState("error");
});
