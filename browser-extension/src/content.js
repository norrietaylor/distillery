/**
 * Content Script for the Distillery Browser Extension.
 *
 * Runs on all pages at document_end (after vendor/readability.js is injected).
 *
 * Responsibilities:
 * - Extract page metadata: title, URL, meta description, Open Graph tags.
 * - Extract full article text via Readability.js.
 * - Capture any user-selected text.
 * - Respond to chrome.runtime.onMessage with type "extractContent".
 */

/* global Readability */

// ---------------------------------------------------------------------------
// Metadata extraction helpers
// ---------------------------------------------------------------------------

/**
 * Get the content of a <meta> tag by name.
 *
 * @param {string} name - The meta tag name attribute value.
 * @returns {string} The content value, or empty string if not found.
 */
function getMetaByName(name) {
  const el = document.querySelector(`meta[name="${name}"]`);
  return el ? (el.getAttribute('content') || '') : '';
}

/**
 * Get the content of an Open Graph <meta> tag by property.
 *
 * @param {string} property - The meta tag property attribute value (e.g. "og:title").
 * @returns {string} The content value, or empty string if not found.
 */
function getOgMeta(property) {
  const el = document.querySelector(`meta[property="${property}"]`);
  return el ? (el.getAttribute('content') || '') : '';
}

/**
 * Extract full article text using Readability.js.
 *
 * Uses a deep clone of the document to avoid mutating the live DOM.
 * Returns null if Readability is unavailable or parsing fails.
 *
 * @returns {{ title: string, textContent: string, excerpt: string } | null}
 */
function extractReadability() {
  if (typeof Readability === 'undefined') {
    return null;
  }

  try {
    const docClone = document.cloneNode(true);
    const reader = new Readability(docClone);
    return reader.parse();
  } catch (_err) {
    return null;
  }
}

/**
 * Extract all page metadata and article content.
 *
 * Returns a structured object suitable for use by the popup or background
 * service worker when constructing a Distillery bookmark entry.
 *
 * @returns {{
 *   title: string,
 *   url: string,
 *   description: string,
 *   ogTitle: string,
 *   ogDescription: string,
 *   ogImage: string,
 *   articleText: string | null,
 *   selectedText: string
 * }}
 */
function extractContent() {
  const title = document.title || '';
  const url = window.location.href;
  const metaDescription = getMetaByName('description');
  const ogTitle = getOgMeta('og:title');
  const ogDescription = getOgMeta('og:description');
  const ogImage = getOgMeta('og:image');
  const selectedText = window.getSelection().toString();

  // Prefer meta description; fall back to OG description.
  const description = metaDescription || ogDescription;

  // Run Readability extraction.
  const readabilityResult = extractReadability();
  const articleText = readabilityResult ? (readabilityResult.textContent || null) : null;

  return {
    title,
    url,
    description,
    ogTitle,
    ogDescription,
    ogImage,
    articleText,
    selectedText,
  };
}

// ---------------------------------------------------------------------------
// Message listener
// ---------------------------------------------------------------------------

/**
 * Listen for "extractContent" messages from the background service worker
 * or popup and respond with extracted page metadata.
 *
 * The caller receives:
 *   { status: 'ok', data: { title, url, description, ogTitle, ogDescription,
 *                            ogImage, articleText, selectedText } }
 */
chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  if (request.type === 'extractContent') {
    try {
      const data = extractContent();
      sendResponse({ status: 'ok', data });
    } catch (err) {
      sendResponse({ status: 'error', error: err.message });
    }
    // Return false — response is sent synchronously.
    return false;
  }
});
