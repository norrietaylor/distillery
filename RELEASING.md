# Releasing Distillery

This document describes the release process for the Distillery MCP server and plugin.

## Release Chain

Creating a GitHub release triggers three automated workflows:

```text
GitHub Release (tag: vX.Y.Z)
  ├─ pypi-publish.yml
  │   ├─ Build sdist + wheel
  │   ├─ Publish to PyPI (distillery-mcp)
  │   ├─ Stamp version in server.json, plugin.json, marketplace.json
  │   ├─ Publish to MCP Registry
  │   └─ Publish to Smithery
  └─ changelog.yml
      ├─ Generate CHANGELOG.md via git-cliff
      └─ Commit to main
```

Users install the server via `pip install distillery-mcp` or `uvx distillery-mcp`, both pulling from PyPI.

## Pre-Release Checklist

1. **Version bump** — Update `version` in `pyproject.toml`:

   ```bash
   # Edit pyproject.toml [project] section
   version = "X.Y.Z"
   ```

2. **Version consistency** — Ensure these files match (the release workflow stamps plugin manifests and server.json automatically, but pyproject.toml is the source of truth):

   | File | Field | Updated by |
   |------|-------|-----------|
   | `pyproject.toml` | `version` | Manual (pre-release) |
   | `.claude-plugin/plugin.json` | `version` | Release workflow |
   | `.claude-plugin/marketplace.json` | `plugins[0].version` | Release workflow |
   | `server.json` | `version`, `packages[].version` | Release workflow |

3. **Merge all PRs** — Ensure all feature branches for this release are merged to `main`.

4. **Tests pass** — Verify CI is green on `main`:

   ```bash
   pytest --cov=src/distillery --cov-fail-under=80
   mypy --strict src/distillery/
   ruff check src/ tests/
   ```

5. **Skill compatibility** — If new MCP tools were added, ensure skills that use them have `min_server_version` in their frontmatter.

## Cutting the Release

### Step 1: Create and push the tag

```bash
# IMPORTANT: Tag format is vX.Y.Z (no extra dots, no prefix other than 'v')
# The release workflow extracts the version with: ${GITHUB_REF#refs/tags/v}
# Wrong: v.0.2.1 → extracts ".0.2.1"
# Right: v0.2.1  → extracts "0.2.1"

git checkout main
git pull origin main
git tag v0.2.1
git push origin v0.2.1
```

### Step 2: Create the GitHub release

```bash
gh release create v0.2.1 \
  --title "v0.2.1 — Short Description" \
  --generate-notes
```

Or create via the GitHub UI at `https://github.com/norrietaylor/distillery/releases/new`.

This triggers pypi-publish.yml and changelog.yml automatically.

### Step 3: Verify

1. **PyPI**: Check https://pypi.org/project/distillery-mcp/ for the new version
2. **Install**: `pip install distillery-mcp==X.Y.Z` or `uvx distillery-mcp --version`
3. **MCP Registry**: Verify the server listing is updated
4. **Changelog**: Check that CHANGELOG.md was auto-committed to main

## Deploying the Hosted Server

The hosted MCP server at `distillery-mcp.fly.dev` is deployed separately via the [distill_ops](https://github.com/norrietaylor/distill_ops) repo. After a PyPI release:

```bash
# In the distill_ops repo
fly deploy --app distillery-mcp
```

## Versioning

Follow [Semantic Versioning](https://semver.org/):

- **Patch** (0.2.1 → 0.2.2): Bug fixes, doc updates, no new MCP tools or skills
- **Minor** (0.2.x → 0.3.0): New MCP tools, new skills, new store methods, migration additions
- **Major** (0.x → 1.0): Breaking protocol changes, migration format changes, removed tools

## Tag Format

**The tag MUST be `vX.Y.Z`** — exactly `v` followed by semver digits.

The release workflow extracts the version number using `${GITHUB_REF#refs/tags/v}`, which strips the leading `v`. Any deviation (e.g., `v.0.2.1`, `ver0.2.1`) produces a malformed version string that breaks PyPI metadata, MCP Registry publishing, and plugin manifest stamping.

## Fixing a Bad Tag

If a tag was created with the wrong format:

```bash
# Delete the bad tag locally and remotely
git tag -d v.0.2.1
git push origin :refs/tags/v.0.2.1

# Delete the GitHub release (if created)
gh release delete v.0.2.1 --yes

# Create the correct tag
git tag v0.2.1 <commit-sha>
git push origin v0.2.1

# Re-create the release
gh release create v0.2.1 --title "v0.2.1 — Description" --generate-notes
```
