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
// Feed detection
// ---------------------------------------------------------------------------

/**
 * Detect RSS/Atom feed links and GitHub repository URLs on the current page.
 *
 * Queries <link rel="alternate" type="application/rss+xml|application/atom+xml">
 * elements and checks if the current URL matches a GitHub repo pattern.
 *
 * @returns {Array<{ url: string, title: string, source_type: 'rss'|'atom'|'github' }>}
 */
function detectFeeds() {
  const feeds = [];

  // Query all <link rel="alternate"> elements with RSS or Atom types.
  const linkEls = document.querySelectorAll(
    'link[rel="alternate"][type*="rss"], link[rel="alternate"][type*="atom"]'
  );

  linkEls.forEach((el) => {
    const href = el.getAttribute('href');
    if (!href) return;

    const type = (el.getAttribute('type') || '').toLowerCase();
    const title = el.getAttribute('title') || document.title || '';
    const source_type = type.includes('atom') ? 'atom' : 'rss';

    // Resolve relative URLs against the page origin.
    let url = href;
    try {
      url = new URL(href, window.location.href).href;
    } catch (_err) {
      // href was not a valid URL; skip.
      return;
    }

    feeds.push({ url, title, source_type });
  });

  // Check if the current page is a GitHub repository.
  const githubRepoPattern = /^https?:\/\/github\.com\/([^/]+)\/([^/?#]+)\/?([^/?#]*)$/;
  const match = window.location.href.match(githubRepoPattern);
  if (match) {
    const owner = match[1];
    const repo = match[2];
    // Exclude known non-repo paths like github.com/owner/repo/issues etc.
    // Only include if it looks like a root repo page or a common sub-path.
    feeds.push({
      url: `https://github.com/${owner}/${repo}`,
      title: `${owner}/${repo}`,
      source_type: 'github',
    });
  }

  return feeds;
}

/**
 * Run feed detection and notify the background service worker.
 *
 * Sends a "feedsDetected" message with the array of detected feeds.
 * Called on DOMContentLoaded (or immediately if DOM is already ready).
 */
function notifyFeedsDetected() {
  const feeds = detectFeeds();
  chrome.runtime.sendMessage({ type: 'feedsDetected', feeds });
}

// Run detection when the DOM is fully parsed.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', notifyFeedsDetected);
} else {
  // document_end injection: DOM is already ready.
  notifyFeedsDetected();
}

// ---------------------------------------------------------------------------
// Message listener
// ---------------------------------------------------------------------------

/**
 * Listen for "extractContent" and "detectFeeds" messages from the background
 * service worker or popup.
 *
 * "extractContent" response:
 *   { status: 'ok', data: { title, url, description, ogTitle, ogDescription,
 *                            ogImage, articleText, selectedText } }
 *
 * "detectFeeds" response:
 *   { status: 'ok', data: Array<{ url, title, source_type }> }
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

  if (request.type === 'detectFeeds') {
    try {
      const data = detectFeeds();
      sendResponse({ status: 'ok', data });
    } catch (err) {
      sendResponse({ status: 'error', error: err.message });
    }
    return false;
  }
});
