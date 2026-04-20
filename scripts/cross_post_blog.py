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


def parse(path: str) -> tuple[dict, str]:
    text = Path(path).read_text()
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise SystemExit(f"{path}: no YAML frontmatter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = m.group(2).lstrip()
    if not fm.get("title"):
        raise SystemExit(f"{path}: frontmatter missing 'title'")
    return fm, body


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"{url} -> HTTP {e.code}: {body}") from e


def post_devto(fm: dict, body: str, cover_url: str, api_key: str) -> dict:
    tags = [str(t) for t in (fm.get("tags") or [])][:DEVTO_TAG_LIMIT]
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
    tags = [{"slug": str(t).lower(), "name": str(t)} for t in (fm.get("tags") or [])]
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

    if dev_key:
        r = post_devto(fm, body, cover, dev_key)
        print(f"dev.to: {r.get('url') or r}")
    else:
        print("DEV_API_KEY missing; skipping dev.to", file=sys.stderr)

    if hn_pat and hn_pub:
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
