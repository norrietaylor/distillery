"""Bookmark service — fetch, summarise, dedup-check, and store a URL."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from distillery.models import Entry, EntrySource, EntryType
from distillery.store.protocol import DistilleryStore

from .ssrf import SSRFError, validate_url

# ── Request / Response types ──────────────────────────────────────────────────


@dataclass
class BookmarkRequest:
    url: str
    tags: list[str]
    project: str
    author: str
    force: bool = False  # bypass duplicate check


@dataclass
class BookmarkResult:
    entry_id: str
    summary: str
    tags: list[str]
    duplicate: bool = False
    existing_id: str | None = None
    similarity: float | None = None


@dataclass
class DuplicateFound:
    existing_id: str
    similarity: float


# ── Service ───────────────────────────────────────────────────────────────────


class BookmarkService:
    """
    Orchestrates the bookmark workflow:
      1. SSRF-safe URL fetch
      2. Summarisation via Claude API
      3. Dedup check
      4. Store
    """

    def __init__(
        self,
        store: DistilleryStore,
        anthropic_api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        max_content_chars: int = 6000,
    ) -> None:
        self._store = store
        self._api_key = anthropic_api_key
        self._model = model
        self._max_chars = max_content_chars

    async def bookmark(self, req: BookmarkRequest) -> BookmarkResult:
        # 1. Validate URL (SSRF guard)
        try:
            validate_url(req.url)
        except SSRFError as exc:
            raise ValueError(str(exc)) from exc

        # 2. Fetch page content
        content = await self._fetch(req.url)

        # 3. Summarise
        summary = await self._summarise(req.url, content)

        # 4. Dedup check
        if not req.force:
            dup = await self._check_dup(req.url, summary)
            if dup:
                return BookmarkResult(
                    entry_id="",
                    summary=summary,
                    tags=[],
                    duplicate=True,
                    existing_id=dup.existing_id,
                    similarity=dup.similarity,
                )

        # 5. Build tags
        domain = _domain_tag(req.url)
        project_tags = [f"project/{req.project}/references"] if req.project else []
        tags = list(
            {
                f"source/bookmark/{domain}",
                *req.tags,
                *project_tags,
            }
        )

        # 6. Store
        entry = Entry(
            content=summary,
            entry_type=EntryType.BOOKMARK,
            author=req.author,
            project=req.project,
            tags=tags,
            source=EntrySource.MANUAL,
            metadata={"url": req.url, "domain": domain},
        )
        entry_id = await self._store.store(entry)

        return BookmarkResult(
            entry_id=entry_id,
            summary=summary,
            tags=tags,
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _fetch(self, url: str) -> str:
        """Fetch URL and return plain-text content (HTML stripped)."""
        headers = {"User-Agent": ("Distillery/0.2 (+https://github.com/norrietaylor/distillery)")}
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            raw_html = response.text

        return _strip_html(raw_html)[: self._max_chars]

    async def _summarise(self, url: str, content: str) -> str:
        """Call Claude API to generate a 2-4 sentence summary."""
        import anthropic  # imported lazily — only required with [server] extra

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        prompt = (
            f"Summarise the following web page in 2-4 sentences, "
            f"then list 3-5 key bullet points.\n\n"
            f"URL: {url}\n\n"
            f"Content:\n{content}"
        )

        message = await client.messages.create(
            model=self._model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text: str = message.content[0].text
        return text

    async def _check_dup(self, url: str, summary: str) -> DuplicateFound | None:
        """Return DuplicateFound if a similar entry already exists."""
        query = f"{url}\n{summary}"
        results = await self._store.find_similar(query, threshold=0.80, limit=5)
        if results:
            top = results[0]
            return DuplicateFound(
                existing_id=top.entry.id or "",
                similarity=top.score,
            )
        return None


# ── HTML stripping ─────────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s{2,}")


def _strip_html(raw: str) -> str:
    text = _SCRIPT_RE.sub("", raw)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _domain_tag(url: str) -> str:
    """Convert a URL hostname to a tag-safe slug: 'github.com' → 'github-com'."""
    host = urlparse(url).hostname or "unknown"
    host = re.sub(r"^www\.", "", host)
    return re.sub(r"[^a-z0-9]", "-", host.lower())
