#!/usr/bin/env python3
"""Cross-post a dev.to-style markdown blog to dev.to and Hashnode.

Reads a markdown file with YAML frontmatter (title, description, tags,
canonical_url) and publishes to dev.to + Hashnode with the canonical URL
preserved. Cover image URL is taken from COVER_IMAGE_URL env var.

Secrets expected in env:
  DEV_API_KEY, HASHNODE_PAT, HASHNODE_PUBLICATION_ID
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
DEVTO_TAG_LIMIT = 4
HTTP_TIMEOUT_SECONDS = 30


def parse(path: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_markdown) parsed from a .md file."""
    text = Path(path).read_text()
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise SystemExit(f"{path}: no YAML frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}
    if not isinstance(fm, dict):
        raise SystemExit(f"{path}: YAML frontmatter must be a mapping")
    body = m.group(2).lstrip()
    if not fm.get("title"):
        raise SystemExit(f"{path}: frontmatter missing 'title'")
    canonical = fm.get("canonical_url")
    if not isinstance(canonical, str) or not canonical.strip():
        raise SystemExit(f"{path}: frontmatter missing 'canonical_url'")
    return fm, body


def _normalize_tags(raw: object) -> list[str]:
    """Coerce frontmatter `tags` (list, scalar, or None) into a list of non-empty strings."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    raise SystemExit("frontmatter 'tags' must be a list or comma-separated string")


def _get_json(url: str, headers: dict, allow_statuses: tuple[int, ...] = ()) -> dict | None:
    """GET url and return parsed JSON; return None for statuses in allow_statuses; exit otherwise."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in allow_statuses:
            return None
        body = e.read().decode(errors="replace")
        raise SystemExit(f"{url} -> HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"{url} -> network error: {e.reason}") from e


def _devto_existing_url(canonical: str, api_key: str) -> str | None:
    """Return the dev.to URL of any existing article whose canonical_url matches, else None.

    Best-effort: if the API key lacks read scope (401/403) we skip the dedup check
    and return None so publishing can proceed.
    """
    page = 1
    while True:
        articles = _get_json(
            f"https://dev.to/api/articles/me/all?per_page=1000&page={page}",
            {"api-key": api_key, "accept": "application/json"},
            allow_statuses=(401, 403),
        )
        if articles is None:
            print(
                "dev.to dedup skipped: API key lacks read scope (401/403). "
                "Generate a key with read_articles scope to enable dedup.",
                file=sys.stderr,
            )
            return None
        if not isinstance(articles, list) or not articles:
            return None
        for a in articles:
            if a.get("canonical_url") == canonical:
                return a.get("url")
        if len(articles) < 1000:
            return None
        page += 1


def _hashnode_existing_url(canonical: str, pat: str, pub_id: str) -> str | None:
    """Return the Hashnode URL of any existing post whose canonicalUrl matches, else None."""
    query = (
        "query Pub($id: ObjectId!, $after: String) {"
        "  publication(id: $id) {"
        "    posts(first: 50, after: $after) {"
        "      edges { node { url canonicalUrl } }"
        "      pageInfo { hasNextPage endCursor }"
        "    }"
        "  }"
        "}"
    )
    after: str | None = None
    while True:
        data = _post_json(
            "https://gql.hashnode.com/",
            {"query": query, "variables": {"id": pub_id, "after": after}},
            {"Authorization": pat},
        )
        if data.get("errors"):
            raise SystemExit(f"Hashnode lookup errors: {json.dumps(data['errors'], indent=2)}")
        conn = (data.get("data") or {}).get("publication", {}).get("posts") or {}
        for edge in conn.get("edges") or []:
            node = edge.get("node") or {}
            if node.get("canonicalUrl") == canonical:
                return node.get("url")
        page_info = conn.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return None
        after = page_info.get("endCursor")


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    """POST JSON to url and return the parsed JSON response; exits on network/HTTP error."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"{url} -> HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"{url} -> network error: {e.reason}") from e


def post_devto(fm: dict, body: str, cover_url: str, api_key: str) -> dict:
    """Publish the post to dev.to and return the API response."""
    tags = _normalize_tags(fm.get("tags"))[:DEVTO_TAG_LIMIT]
    payload = {
        "article": {
            "title": fm["title"],
            "body_markdown": body,
            "published": True,
            "canonical_url": fm.get("canonical_url"),
            "description": fm.get("description", ""),
            "tags": tags,
            "main_image": cover_url,
        }
    }
    return _post_json("https://dev.to/api/articles", payload, {"api-key": api_key})


def post_hashnode(fm: dict, body: str, cover_url: str, pat: str, pub_id: str) -> dict:
    """Publish the post to Hashnode via GraphQL and return the post object."""
    tags = [{"slug": t.lower(), "name": t} for t in _normalize_tags(fm.get("tags"))]
    query = (
        "mutation PublishPost($input: PublishPostInput!) {"
        "  publishPost(input: $input) { post { id slug url } }"
        "}"
    )
    variables = {
        "input": {
            "publicationId": pub_id,
            "title": fm["title"],
            "contentMarkdown": body,
            "tags": tags,
            "originalArticleURL": fm.get("canonical_url"),
            "coverImageOptions": {"coverImageURL": cover_url},
            "subtitle": fm.get("description", ""),
        }
    }
    data = _post_json(
        "https://gql.hashnode.com/",
        {"query": query, "variables": variables},
        {"Authorization": pat},
    )
    if data.get("errors"):
        raise SystemExit(f"Hashnode errors: {json.dumps(data['errors'], indent=2)}")
    return data["data"]["publishPost"]["post"]


def main() -> int:
    """CLI entry point: publish a single markdown file to dev.to and Hashnode."""
    if len(sys.argv) != 2:
        print("usage: cross_post_blog.py <path-to-markdown>", file=sys.stderr)
        return 2

    path = sys.argv[1]
    fm, body = parse(path)

    cover = os.environ.get("COVER_IMAGE_URL")
    if not cover:
        raise SystemExit("COVER_IMAGE_URL env var is required")

    dev_key = os.environ.get("DEV_API_KEY")
    hn_pat = os.environ.get("HASHNODE_PAT")
    hn_pub = os.environ.get("HASHNODE_PUBLICATION_ID")

    canonical = fm["canonical_url"]

    if dev_key:
        existing = _devto_existing_url(canonical, dev_key)
        if existing:
            print(f"dev.to: already posted ({existing}); skipping")
        else:
            r = post_devto(fm, body, cover, dev_key)
            print(f"dev.to: {r.get('url') or r}")
    else:
        print("DEV_API_KEY missing; skipping dev.to", file=sys.stderr)

    if hn_pat and hn_pub:
        existing = _hashnode_existing_url(canonical, hn_pat, hn_pub)
        if existing:
            print(f"hashnode: already posted ({existing}); skipping")
        else:
            r = post_hashnode(fm, body, cover, hn_pat, hn_pub)
            print(f"hashnode: {r.get('url') or r}")
    else:
        print(
            "HASHNODE_PAT or HASHNODE_PUBLICATION_ID missing; skipping hashnode",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
