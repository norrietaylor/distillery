# /pour — Multi-Entry Synthesis

Performs multi-pass retrieval and synthesizes findings into a structured narrative with inline citations, contradiction flags, and knowledge gap analysis.

## Usage

```text
/pour how does our auth system work?
/pour --project billing payment processing
```

**Trigger phrases:** "synthesize", "what's the full picture on", "deep dive into"

## When to Use

- Building a comprehensive understanding of a topic from multiple entries
- Preparing for a design review or decision by gathering all related knowledge
- Identifying contradictions or gaps in the team's knowledge

## How It Works

1. **Broad search** — initial semantic search across the knowledge base (up to 20 results)
2. **Follow-up searches** — up to 3 additional queries for related concepts found in pass 1
3. **Gap-filling** — up to 2 targeted queries for referenced but missing topics
4. **Synthesis** — combines all unique entries into a structured narrative

If fewer than 2 entries are found, falls back to a standard `/recall`-style display.

## Options

| Option | Description |
|--------|-------------|
| `--project <name>` | Scope synthesis to a specific project |

## Output

```markdown
# Pour: Authentication System

## Summary
The authentication system uses GitHub OAuth as an identity gate [Entry a1b2c3d4],
with tokens verified via the /user endpoint [Entry e5f6g7h8]...

## Timeline
- 2026-03-10: Initial OAuth implementation decided [Entry a1b2c3d4]
- 2026-03-15: FastMCP GitHubProvider integrated [Entry i9j0k1l2]

## Key Decisions
- Use `user` scope only — no repo access [Entry a1b2c3d4]
- Tokens stored locally, never on server [Entry e5f6g7h8]

## Contradictions
- Entry a1b2c3d4 says tokens expire after 24h, but Entry e5f6g7h8
  says GitHub tokens are valid indefinitely

## Knowledge Gaps
- No entries found about token refresh behavior
- Multi-team RBAC design not yet documented

## Sources
| # | Entry ID | Type | Date | Similarity |
|---|----------|------|------|------------|
| 1 | a1b2c3d4 | session | 2026-03-10 | 95% |
| 2 | e5f6g7h8 | bookmark | 2026-03-12 | 88% |
```

### Citations

Every claim is traced back to a source using `[Entry <short-id>]` format (first 8 characters of the UUID). Empty sections are omitted.

### Interactive Refinement

After the initial synthesis, you can ask follow-up questions (up to 5 rounds). Each refinement is appended as an addendum.

## Tips

- `/pour` is best for broad topics — use `/recall` for quick lookups
- If only one author contributed, the output includes a perspective bias note
- Entries are deduplicated by ID across all search passes
