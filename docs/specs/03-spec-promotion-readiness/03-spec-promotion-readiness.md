# 03-spec-promotion-readiness

## Introduction/Overview

Prepare the Distillery repository for external promotion by filling quality gaps that affect first impressions. This covers two areas: README polish (badges, demo recording) and a security policy. These are the gaps between "working project" and "project ready for Hacker News, PyPI, and MCP directory listings."

## Goals

1. README communicates project maturity at a glance via badges and a demo recording
2. Security policy exists for responsible vulnerability disclosure via GitHub Security Advisories
3. Supporting files (`.env.example`) are in place for the promotion plan

## User Stories

- As a **visitor from Hacker News or PyPI**, I want to see badges and a demo recording in the README so that I can quickly assess project maturity and understand what it does.
- As a **security researcher**, I want a SECURITY.md file so that I know how to responsibly report vulnerabilities.
## Demoable Units of Work

### Unit 1: README Polish — Badges and Demo Recording

**Purpose:** Add visual signals of project maturity (badges) and a terminal demo recording (asciinema → GIF) so first-time visitors immediately understand what Distillery does and that it's actively maintained.

**Functional Requirements:**
- The README shall include a badge row between the nav links and the "---" separator, containing three shields.io badges: PyPI version (`https://img.shields.io/pypi/v/distillery`), License (`https://img.shields.io/github/license/norrietaylor/distillery`), and Python version (`https://img.shields.io/badge/python-3.11%2B-blue`).
- Each badge shall link to its corresponding resource (PyPI page, LICENSE file, python.org).
- The README shall include a demo section (after "What is Distillery?" and before "Skills") containing an embedded GIF or animated SVG showing a `/distill` → `/recall` flow in a terminal session.
- The demo recording shall be created using `asciinema rec` and converted to GIF or animated SVG using `agg` (asciinema GIF generator) or `svg-term-cli`.
- The demo recording asset shall be stored at `docs/assets/distillery-demo.gif` (or `.svg`).
- The demo section shall include a brief caption explaining what the recording shows.
- The system shall include an `.env.example` file at the repository root with placeholder values and comments documenting each variable (JINA_API_KEY, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, and any others referenced in the codebase).

**Proof Artifacts:**
- File: `README.md` contains three shields.io badge image links in the header section
- File: `README.md` contains an `<img>` or `![demo]` reference to `docs/assets/distillery-demo.gif`
- File: `docs/assets/distillery-demo.gif` (or `.svg`) exists and is viewable
- File: `.env.example` exists at repository root with all required variables documented

### Unit 2: SECURITY.md — Vulnerability Disclosure Policy

**Purpose:** Establish a responsible disclosure channel so security researchers know how to report vulnerabilities privately before the project gets public traffic.

**Functional Requirements:**
- The repository shall include a `SECURITY.md` file at the root following GitHub's [security policy format](https://docs.github.com/en/code-security/getting-started/adding-a-security-policy-to-your-repository).
- The policy shall direct reporters to use GitHub Security Advisories (Security tab → "Report a vulnerability") as the primary disclosure channel.
- The policy shall state which versions are supported (currently: v0.1.x on the `main` branch).
- The policy shall include a "What to report" section listing: authentication/authorization bypasses, data exposure (knowledge entries accessible without authorization), injection vulnerabilities in DuckDB queries, MCP transport security issues, and dependency vulnerabilities.
- The policy shall include a "What NOT to report" section noting: the demo server at `distillery-mcp.fly.dev` is explicitly not production-grade and known-limitation issues are not security vulnerabilities.
- The policy shall commit to an initial response time (e.g., 72 hours) and a resolution target (e.g., 30 days for confirmed issues).
- GitHub's private vulnerability reporting shall be enabled in repository settings (Security tab → enable private vulnerability reporting).

**Proof Artifacts:**
- File: `SECURITY.md` exists at repository root with disclosure instructions
- File: `SECURITY.md` references GitHub Security Advisories as the reporting mechanism
- URL: Repository Security tab shows "Private vulnerability reporting" enabled

## Non-Goals (Out of Scope)

- Increasing test coverage (already at 83%, above the 80% CI threshold)
- Publishing to PyPI (covered by the promotion plan's Phase 1, requires manual account setup)
- Submitting to MCP directories (manual process, not automatable via code)
- Social media account creation or posting
- Video production (asciinema recording is terminal-native, not video editing)
- Changelog automation with git-cliff (Phase 5 of promotion plan)
- README shields.io badges for CI status or coverage (kept minimal per user preference)

## Design Considerations

- Badge row should use HTML `<p align="center">` to match the existing README header style
- Demo GIF should be ≤2MB to avoid slow loading on GitHub (use `agg` with optimized settings or animated SVG)
## Repository Standards

- **Conventional Commits**: `docs(readme):`, `docs(security):`
- **Markdown**: Follow existing README formatting (centered HTML headers, GFM tables)
- **Assets**: Store in `docs/assets/` alongside existing logos and diagrams

## Technical Considerations

- **asciinema + agg**: `asciinema rec` captures terminal sessions as `.cast` files; `agg` converts to GIF. Both are available via pip/cargo. The `.cast` file should be kept in `docs/assets/` for re-recording.
- **shields.io badges**: Static badges, no CI integration needed. PyPI badge auto-updates once the package is published; until then it will show "not found" — this is acceptable and expected.
- **Demo recording content**: The recording should use the local stdio transport against a seeded test database, not the production demo server, to ensure consistent output.

## Security Considerations

- The `.env.example` file must contain only placeholder values (e.g., `your-api-key-here`), never real credentials.
- The SECURITY.md must not disclose specific vulnerability details or attack vectors — it's a policy document, not a vulnerability report.
## Success Metrics

| Metric | Target |
|--------|--------|
| README badges | 3 badges visible (PyPI, License, Python) |
| Demo recording | ≤2MB GIF/SVG embedded in README |
| SECURITY.md | Present with GitHub Security Advisories link |
| .env.example | All required env vars documented |

## Open Questions

No open questions at this time.
