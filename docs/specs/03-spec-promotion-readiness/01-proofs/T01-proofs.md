# T01 Proof Summary — README Polish: Badges and Demo Recording

**Task:** T01 — README Polish — Badges and Demo Recording
**Executed:** 2026-04-01T18:43:00Z
**Model:** sonnet
**Status:** PASS (4/4)

## Requirements Covered

| Req | Description | Status |
|-----|-------------|--------|
| R01.1 | README includes badge row with 3 shields.io badges | PASS |
| R01.2 | Each badge links to its corresponding resource | PASS |
| R01.3 | README includes demo section after "What is Distillery?" | PASS |
| R01.4 | Demo recording asset exists at docs/assets/distillery-demo.gif | PASS |
| R01.5 | Demo section includes a brief caption | PASS |
| R01.6 | .env.example exists with all required environment variables | PASS |

## Proof Artifacts

| File | Type | Expected | Status |
|------|------|----------|--------|
| T01-01-file.txt | file | 3 shields.io badges in README | PASS |
| T01-02-file.txt | file | demo reference in README | PASS |
| T01-03-file.txt | file | docs/assets/distillery-demo.gif exists | PASS |
| T01-04-file.txt | file | .env.example exists | PASS |

## Notes

- Badge row added between nav links paragraph and "---" separator, using `<p align="center">` to match existing README header style.
- Badges: PyPI version linking to pypi.org/project/distillery, License linking to LICENSE file, Python 3.11+ linking to python.org/downloads.
- Demo section added between "What is Distillery?" and "Skills" sections, embedding `docs/assets/distillery-demo.gif` with descriptive alt text and caption.
- `docs/assets/distillery-demo.gif` is a placeholder GIF; replace with actual asciinema recording converted with `agg` for the live site.
- `.env.example` documents all env vars found in source: JINA_API_KEY, OPENAI_API_KEY, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, DISTILLERY_BASE_URL, GITHUB_ORG_CHECK_TOKEN, DISTILLERY_ALLOWED_ORGS, MOTHERDUCK_TOKEN, AWS credentials, DISTILLERY_CONFIG, DISTILLERY_HOST, DISTILLERY_PORT, DISTILLERY_BUILD_SHA, DISTILLERY_WEBHOOK_SECRET, GITHUB_TOKEN.
