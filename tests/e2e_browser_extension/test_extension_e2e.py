from __future__ import annotations

import argparse
import asyncio
import os
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import sys
from pathlib import Path as _Path

# Allow running as a standalone script (python3 tests/e2e_browser_extension/test_extension_e2e.py).
sys.path.insert(0, str(_Path(__file__).resolve().parent))

from mcp_http_client import MCPHTTPClient  # noqa: E402

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - only relevant when running without Playwright
    async_playwright = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]
EXTENSION_DIR = REPO_ROOT / "browser-extension"
TEST_PAGE_PATH = REPO_ROOT / "tests/e2e_browser_extension/assets/test_page.html"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _ThreadedHTTPServer(HTTPServer):
    daemon_threads = True


def _start_test_page_server(*, feed_url: str) -> tuple[HTTPServer, str, threading.Thread]:
    """
    Start a small HTTP server that serves the test HTML with dynamic feed_url
    substitution (replacing `__FEED_URL__` in the file content).
    """

    html_template = TEST_PAGE_PATH.read_text(encoding="utf-8")

    unique_html = html_template.replace("__FEED_URL__", feed_url)

    port = _free_port()
    server_url = f"http://127.0.0.1:{port}/test_page.html"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/test_page.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(unique_html.encode("utf-8"))
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            # Keep test output clean.
            return

    httpd = _ThreadedHTTPServer(("127.0.0.1", port), Handler)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    return httpd, server_url, t


def _extract_extension_id_from_service_worker_url(service_worker_url: str) -> str:
    """
    Example:
      chrome-extension://<EXT_ID>/src/background.js
    """

    prefix = "chrome-extension://"
    if not service_worker_url.startswith(prefix):
        raise ValueError(f"Unexpected service worker URL: {service_worker_url!r}")
    rest = service_worker_url[len(prefix) :]
    return rest.split("/", 1)[0]


async def _wait_for_extension_service_worker(context: Any, timeout_s: float = 15.0) -> str:
    start = time.time()
    while time.time() - start < timeout_s:
        for sw in context.service_workers:
            try:
                if "src/background.js" in sw.url:
                    return sw.url
            except Exception:
                continue
        await asyncio.sleep(0.25)
    raise TimeoutError("Timed out waiting for extension background service worker")


async def _send_runtime_message(page: Any, payload: dict[str, Any]) -> dict[str, Any]:
    # Execute in the extension page context (page must be an extension URL).
    js = """
      async (payload) => {
        return await new Promise((resolve) => {
          chrome.runtime.sendMessage(payload, (response) => {
            const err = chrome.runtime.lastError ? chrome.runtime.lastError.message : null;
            if (err) resolve({ __error: err });
            else resolve(response);
          });
        });
      }
    """
    return await page.evaluate(js, payload)


async def _get_auth_from_extension_storage(page: Any) -> dict[str, Any]:
    js = """
      async () => {
        return await chrome.storage.local.get(['authToken', 'authUsername']);
      }
    """
    return await page.evaluate(js)


async def _extract_content_from_test_tab(extension_page: Any, test_page_url: str) -> dict[str, Any]:
    """
    Use chrome.tabs.sendMessage(type='extractContent') to invoke the content script
    on the test tab.
    """

    js = """
      async ({testPageUrl}) => {
        const tabs = await new Promise((resolve) => {
          chrome.tabs.query({ url: testPageUrl }, (res) => resolve(res));
        });

        if (!tabs || tabs.length === 0) {
          return { __error: `No tab found for url: ${testPageUrl}` };
        }

        const tabId = tabs[0].id;
        const resp = await new Promise((resolve) => {
          chrome.tabs.sendMessage(tabId, { type: 'extractContent' }, (r) => {
            const err = chrome.runtime.lastError ? chrome.runtime.lastError.message : null;
            if (err) resolve({ __error: err });
            else resolve(r);
          });
        });
        return resp;
      }
    """
    return await extension_page.evaluate(js, {"testPageUrl": test_page_url})


async def _wait_for_connection_connected(extension_page: Any, timeout_s: float = 20.0) -> dict[str, Any]:
    start = time.time()
    while time.time() - start < timeout_s:
        state = await _send_runtime_message(extension_page, {"action": "getConnectionStatus"})
        if (
            state
            and state.get("status") == "ok"
            and state.get("data")
            and state["data"].get("connected") is True
        ):
            return state["data"]
        await asyncio.sleep(0.5)
    raise TimeoutError("Timed out waiting for extension to connect to MCP server")


async def _set_extension_options(
    options_page: Any,
    *,
    remote_server_url: str,
    local_mcp_port: int,
    auto_detect_local: bool,
    default_project: str,
    default_tags: str,
    github_client_id: str,
) -> None:
    # Wait for the form to be ready (caller must have already navigated).
    await options_page.locator("#remoteServerUrl").wait_for(state="visible", timeout=5000)

    await options_page.locator("#remoteServerUrl").fill(remote_server_url)
    await options_page.locator("#localMcpPort").fill(str(local_mcp_port))

    const_is_checked = await options_page.locator("#autoDetectLocal").is_checked()
    if const_is_checked != auto_detect_local:
        await options_page.locator("#autoDetectLocal").click()

    await options_page.locator("#defaultProject").fill(default_project)
    await options_page.locator("#defaultTags").fill(default_tags)
    await options_page.locator("#githubClientId").fill(github_client_id)

    # Submit the form.
    await options_page.locator("button[type='submit']").click()

    # Wait for a visible success message.
    await options_page.wait_for_timeout(500)


async def _bootstrap_auth(args: argparse.Namespace) -> None:
    user_data_dir = args.playwright_profile_dir

    if async_playwright is None:
        raise RuntimeError(
            "Playwright is not installed. Install it with `pip install playwright` "
            "and run `playwright install chromium`."
        )

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            args=[
                f"--disable-extensions-except={EXTENSION_DIR}",
                f"--load-extension={EXTENSION_DIR}",
            ],
        )

        sw_url = await _wait_for_extension_service_worker(context)
        ext_id = _extract_extension_id_from_service_worker_url(sw_url)
        ext_origin = f"chrome-extension://{ext_id}"

        options_page = await context.new_page()
        options_url = f"{ext_origin}/src/options.html"
        await options_page.goto(options_url, wait_until="networkidle")

        await _set_extension_options(
            options_page,
            remote_server_url=args.remote_mcp_url,
            local_mcp_port=args.local_mcp_port,
            auto_detect_local=False,
            default_project=args.default_project,
            default_tags=args.default_tags,
            github_client_id=args.github_client_id,
        )

        # Trigger a reconnect so background picks up the new remote URL.
        # connect() resolves before sendResponse, so connectionState is settled.
        reconnect_resp = await _send_runtime_message(options_page, {"action": "reconnect"})
        conn_data = (reconnect_resp or {}).get("data", {})
        print(f"[bootstrap] connection after reconnect: connected={conn_data.get('connected')} "
              f"serverType={conn_data.get('serverType')} username={conn_data.get('username')}")

        if conn_data.get("username"):
            print(f"[bootstrap] Already authenticated as: {conn_data['username']}")
            await context.close()
            return

        # Open the popup and switch to the Status tab where the sign-in button lives.
        popup_page = await context.new_page()
        await popup_page.goto(f"{ext_origin}/src/popup.html", wait_until="networkidle")
        await popup_page.wait_for_timeout(1000)

        # The sign-in button is inside the Status tab (not active by default).
        await popup_page.locator("button[data-tab='status']").click()
        await popup_page.wait_for_timeout(500)

        signin_btn = popup_page.locator("#signin-btn")
        await signin_btn.wait_for(state="visible", timeout=20000)
        print("[bootstrap] Click 'Sign in with GitHub' in the browser to complete OAuth...")
        await signin_btn.click()

        # Wait for the user to complete the OAuth flow (up to 5 minutes).
        # Use locator polling instead of wait_for_function to avoid CSP eval restriction.
        auth_username_loc = popup_page.locator("#auth-username")
        start = time.time()
        auth_username_text = ""
        while time.time() - start < 300:
            text = await auth_username_loc.text_content()
            if text and text.strip():
                auth_username_text = text
                break
            await asyncio.sleep(1.0)
        if not auth_username_text:
            raise TimeoutError("OAuth did not complete within 5 minutes")
        print(f"[bootstrap] Authenticated as: {auth_username_text.strip()}")

        await context.close()


async def _verify_watch_and_bookmark_via_mcp(
    *,
    auth_token: str,
    remote_mcp_url: str,
    feed_url: str,
    bookmark_tag: str,
    test_page_url: str,
) -> None:
    client = MCPHTTPClient(server_url=remote_mcp_url, auth_token=auth_token)
    await client.initialize()

    # Verify watch source is registered.
    watch_list = await client.call_tool("distillery_watch", {"action": "list"})
    sources = watch_list.get("sources", []) if isinstance(watch_list, dict) else []
    matching = [s for s in sources if isinstance(s, dict) and s.get("url") == feed_url]
    assert matching, f"Expected feed url in watch list: {feed_url!r}. Got: {sources!r}"

    # Verify bookmark tag exists (may fail if the extension currently omits
    # the top-level `author` arg required by distillery_store).
    list_resp = await client.call_tool(
        "distillery_list",
        {
            "entry_type": "bookmark",
            "tags": [bookmark_tag],
            "output_mode": "full",
            "limit": 20,
            "offset": 0,
        },
    )

    entries = list_resp.get("entries", []) if isinstance(list_resp, dict) else []
    assert entries, (
        "Expected bookmark entry to be present for unique tag. "
        f"tag={bookmark_tag!r} test_page_url={test_page_url!r} response={list_resp!r}"
    )


async def _run_e2e(args: argparse.Namespace) -> None:
    user_data_dir = args.playwright_profile_dir

    unique_id = uuid.uuid4().hex[:10]
    feed_url = f"{args.feed_url_base}?e2e={unique_id}"
    bookmark_tag = f"e2e/browser-extension/bookmark-{unique_id}"
    test_page_title = "Distillery E2E Article"

    httpd, test_page_url, _thread = _start_test_page_server(feed_url=feed_url)
    try:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright is not installed. Install it with `pip install playwright` "
                "and run `playwright install chromium`."
            )

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=True,
                args=[
                    f"--disable-extensions-except={EXTENSION_DIR}",
                    f"--load-extension={EXTENSION_DIR}",
                ],
            )

            sw_url = await _wait_for_extension_service_worker(context)
            ext_id = _extract_extension_id_from_service_worker_url(sw_url)
            ext_origin = f"chrome-extension://{ext_id}"

            # Open the test page in a normal tab.
            test_tab = await context.new_page()
            await test_tab.goto(test_page_url)

            # Open an extension page to run chrome.runtime / chrome.tabs APIs.
            extension_page = await context.new_page()
            await extension_page.goto(f"{ext_origin}/src/options.html")

            # Re-load the test tab after opening the extension page, to ensure the
            # last `feedsDetected` message originates from the test page.
            await test_tab.reload()
            await test_tab.wait_for_load_state("domcontentloaded")

            # Ensure extension connects to the configured remote MCP.
            await _wait_for_connection_connected(extension_page)

            # Wait for detected feeds to appear for the active test tab.
            feed_detected: list[dict[str, Any]] = []
            start = time.time()
            while time.time() - start < 20.0:
                detected = await _send_runtime_message(extension_page, {"action": "getDetectedFeeds"})
                if detected and detected["status"] == "ok" and isinstance(detected.get("data"), list):
                    feed_detected = detected["data"]
                    if feed_detected:
                        break
                await asyncio.sleep(0.5)
            assert feed_detected, "Expected the extension to detect at least one feed on the test page"

            matching_feed = next(
                (f for f in feed_detected if isinstance(f, dict) and f.get("url") == feed_url),
                None,
            )
            assert matching_feed, f"Detected feeds did not include unique feed url. Got: {feed_detected!r}"

            # Extract bookmark content from the test page via content script.
            extracted = await _extract_content_from_test_tab(extension_page, test_page_url)
            if extracted.get("__error"):
                raise RuntimeError(f"Content extraction failed: {extracted['__error']}")
            if extracted.get("status") != "ok":
                # content.js responds with { status: 'ok', data: {...} }
                raise RuntimeError(f"Unexpected extractContent response: {extracted!r}")

            extracted_data = extracted["data"]
            # Mirror the extension's buildBookmarkContent logic.
            article_text = extracted_data.get("articleText") or ""
            selected_text = extracted_data.get("selectedText") or ""
            description = extracted_data.get("description") or ""
            title = extracted_data.get("title") or test_page_title
            url = extracted_data.get("url") or test_page_url

            body = selected_text or article_text or description or ""
            lines: list[str] = []
            if title:
                lines.extend([f"# {title}", ""])
            if url:
                lines.extend([f"**URL:** {url}", ""])
            if description:
                lines.extend([f"**Description:** {description}", ""])
            if body:
                lines.extend(["---", "", body])
            content = "\n".join(lines)
            if len(content) > 5000:
                content = content[:5000]

            # Capture auth token from extension storage.
            storage = await _get_auth_from_extension_storage(extension_page)
            auth_token = storage.get("authToken")
            if not auth_token:
                raise RuntimeError("Extension storage did not contain authToken; bootstrap may be required")

            # Perform bookmark save via background message handler.
            bookmark_payload = {
                "action": "bookmark",
                "title": title,
                "url": url,
                "content": content,
                "entry_type": "bookmark",
                "source": "browser-extension",
                "tags": [bookmark_tag],
                "project": args.default_project or None,
                # The extension currently writes author into metadata, not the top-level
                # `author` arg required by distillery_store. We pass it anyway for
                # correctness, but bookmark may still fail (useful signal).
                "author": storage.get("authUsername") or None,
                "metadata": {"url": url, "title": title},
            }

            bookmark_resp = await _send_runtime_message(extension_page, bookmark_payload)
            print(f"[e2e] bookmark response: {bookmark_resp!r}")

            # Perform watch add via background message handler.
            watch_payload = {
                "action": "watchAdd",
                "url": matching_feed["url"],
                "source_type": matching_feed.get("source_type") or "rss",
                "label": matching_feed.get("title") or matching_feed["url"],
            }
            watch_resp = await _send_runtime_message(extension_page, watch_payload)
            print(f"[e2e] watchAdd response: {watch_resp!r}")

            await _verify_watch_and_bookmark_via_mcp(
                auth_token=auth_token,
                remote_mcp_url=args.remote_mcp_url,
                feed_url=feed_url,
                bookmark_tag=bookmark_tag,
                test_page_url=test_page_url,
            )

            await context.close()
    finally:
        httpd.shutdown()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Distillery browser extension E2E harness (authenticated)."
    )
    parser.add_argument(
        "--bootstrap-auth",
        action="store_true",
        help="Run headed OAuth bootstrap once (manual login).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run authenticated E2E: bookmark + watch, then verify via MCP tools.",
    )
    parser.add_argument(
        "--playwright-profile-dir",
        type=Path,
        default=REPO_ROOT / ".playwright-extension-profile",
        help="Persistent Chromium profile dir for extension storage + OAuth.",
    )
    parser.add_argument(
        "--remote-mcp-url",
        default=os.environ.get("DEMO_REMOTE_MCP_URL", "https://distillery-mcp.fly.dev/mcp"),
        help="Remote Distillery MCP base URL (/mcp).",
    )
    parser.add_argument(
        "--github-client-id",
        default=os.environ.get("DEMO_GITHUB_CLIENT_ID", ""),
        help="GitHub OAuth app client ID used by the demo MCP server.",
    )
    parser.add_argument(
        "--local-mcp-port",
        type=int,
        default=8000,
        help="Local MCP port used only for probing (auto-detect is disabled in harness).",
    )
    parser.add_argument(
        "--default-project",
        default="",
        help="Optional project value passed with the bookmark request.",
    )
    parser.add_argument(
        "--default-tags",
        default="",
        help="Optional default tags for the extension options page (used by the extension UI).",
    )
    parser.add_argument(
        "--feed-url-base",
        default="https://example.com/distillery-e2e-feed.xml",
        help="Base feed URL used for uniqueness; harness appends ?e2e=<id>.",
    )
    return parser


async def _main_async() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.bootstrap_auth and not args.run:
        parser.error("Specify either --bootstrap-auth or --run")

    if args.bootstrap_auth and not args.github_client_id:
        raise SystemExit(
            "Missing --github-client-id (or env DEMO_GITHUB_CLIENT_ID). "
            "Needed to configure the extension OAuth client id."
        )

    if args.bootstrap_auth:
        await _bootstrap_auth(args)
        return

    if args.run:
        await _run_e2e(args)
        return


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()

