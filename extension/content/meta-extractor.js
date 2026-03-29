/**
 * Distillery content script — meta extractor
 *
 * Extracts page title, description, and keywords from <meta> tags.
 * Responds to GET_META messages from the popup.
 */

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "GET_META") return;

  const meta = extractMeta();
  sendResponse(meta);
});

function extractMeta() {
  const get = (name) =>
    document.querySelector(`meta[name="${name}"]`)?.getAttribute("content") ??
    document.querySelector(`meta[property="${name}"]`)?.getAttribute("content") ??
    null;

  const title =
    get("og:title") ??
    document.title ??
    null;

  const description =
    get("og:description") ??
    get("description") ??
    get("twitter:description") ??
    null;

  const keywordStr =
    get("keywords") ??
    get("news_keywords") ??
    "";

  const keywords = keywordStr
    .split(/[,;]/)
    .map((k) => k.trim().toLowerCase().replace(/\s+/g, "-"))
    .filter((k) => k.length > 0 && k.length < 40)
    .slice(0, 8);

  return { title, description, keywords };
}
