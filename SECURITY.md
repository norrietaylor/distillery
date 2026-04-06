# Security Policy

## Reporting a Vulnerability

We take security seriously. If you discover a vulnerability in Distillery, please report it responsibly through **GitHub Security Advisories** rather than opening a public issue.

### How to Report

1. Go to the [Distillery repository](https://github.com/norrietaylor/distillery)
2. Click the **Security** tab on the repository page
3. Click **"Report a vulnerability"**
4. Fill in the details and submit

This notifies our security team privately so we can work on a fix before the issue becomes public.

We commit to:
- **Initial response:** Within 72 hours
- **Resolution target:** Within 30 days for confirmed security issues

---

## Supported Versions

Currently, we support the following versions with security updates:

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
| < 0.1.0 | No        |

Security updates are released on the `main` branch and tagged with semver releases on [PyPI](https://pypi.org/project/distillery-mcp/).

---

## What to Report

Please report the following security issues:

- **Authentication/Authorization bypasses** — unauthorized access to knowledge entries or restricted operations
- **Data exposure** — knowledge entries accessible without proper authorization checks
- **Injection vulnerabilities** — DuckDB query injection or prompt injection in LLM-based operations
- **MCP transport issues** — vulnerabilities in stdio or HTTP transport security
- **Dependency vulnerabilities** — known CVEs in transitive dependencies

---

## What NOT to Report

Do NOT report these as security vulnerabilities:

- **Demo server issues** — The public demo at `distillery-mcp.fly.dev` is explicitly not production-grade. Do not store sensitive or confidential data there.
- **Known limitations** — Missing features or intended design constraints (e.g., no end-to-end encryption) are not security vulnerabilities.
- **Low-severity issues** — Spelling errors, missing documentation, or minor UI inconsistencies should be reported as regular issues.

---

## Security Considerations

### Local Deployment

When running Distillery locally:
- Store your `.env` file securely; never commit it to version control
- Use strong API keys (JINA_API_KEY, GITHUB_CLIENT_ID, etc.)
- Run the MCP server over stdio (default) or use HTTPS for HTTP transport

### Team Deployment

For production team deployments:
- Use GitHub OAuth for authentication
- Enable "Private vulnerability reporting" in your repository settings
- Run Distillery on a secure infrastructure (Fly.io, cloud VM, etc.)
- Regularly update dependencies with `uv pip install --upgrade distillery-mcp` or `pip install --upgrade distillery-mcp`

### Dependency Security

Distillery depends on:
- **DuckDB** for data storage
- **Embedding providers** (Jina, OpenAI) for vector embeddings
- **FastMCP** for Model Context Protocol support

We recommend regularly checking for and applying security updates across the dependency tree.

---

## Questions?

If you have questions about this policy, please email the maintainer or open a discussion in the [Issues](https://github.com/norrietaylor/distillery/issues) section.

Thank you for helping keep Distillery secure.
