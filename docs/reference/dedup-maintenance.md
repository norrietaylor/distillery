# Dedup &amp; Merge Maintenance

Distillery can deduplicate and merge entries. Because a merge **bulk-rewrites
the `entries` table** across the variable-length VARCHAR (`content`,
`metadata`, and the dictionary-encoded columns) and the `embedding` column, it
carries a real risk: a torn write or a botched re-encoding pass across a row
group can leave the table corrupt in a way that `SELECT COUNT(*)` **never
detects** — the catalog row-group metadata keeps counting rows whose backing
data pages are gone (see [#584](https://github.com/norrietaylor/distillery/issues/584)).

This page documents the supported dedup/merge operation and the safe snapshot
pattern you should follow when running it manually.

## How merges happen

There is **no standalone dedup script**. Merges are driven through the MCP tool
`distillery_find_similar` with an `accept_action`:

| `accept_action` | Relation written | Rewrites `entries`? |
|-----------------|------------------|---------------------|
| `link`          | `related`        | No (relation only)  |
| `merge`         | `merge_source`   | Yes                 |
| `duplicate`     | `duplicate`      | Yes                 |

`merge` and `duplicate` are the dedup outcomes. The user/agent reviews the
candidates surfaced by `distillery_find_similar` and accepts the match, which
persists the merge relation and folds the duplicate into its canonical entry.

## Built-in integrity guard

After a `merge`/`duplicate` accept, Distillery automatically runs a
**post-rewrite integrity guard** before reporting success:

1. `CHECKPOINT` — flush the WAL and force re-encoding of the touched row groups
   into the main database file.
2. **Read-back** — materialise `id, content, metadata` for the touched rows
   (`SELECT … FROM entries WHERE id = ANY(<touched ids>)`), forcing DuckDB to
   scan the data pages rather than return catalog statistics.
3. **Storage sweep** — `PRAGMA storage_info('entries')` over the table's
   storage metadata.

If any step errors, the operation **fails loud** (raises
`EntriesIntegrityError` in the store; returns an `INTERNAL` error from the MCP
tool) instead of reporting a successful merge over a corrupt table. The same
guard is available directly as `DuckDBStore.verify_entries_readable(entry_ids)`
for any other code path that bulk-rewrites `entries`.

## Snapshot pattern (recommended)

Even with the guard, take a snapshot before a manual dedup session so you can
roll back instantly if anything goes wrong. Snapshot the on-disk database file
while the server is stopped (or right after a `CHECKPOINT`):

```bash
# Stop the server, then snapshot the database file before deduping.
cp ~/.distillery/distillery.db \
   ~/.distillery/distillery.db.pre-dedup-$(date +%Y%m%d-%H%M%S).bak
```

Keep the `.pre-dedup-*` snapshot until you have confirmed the post-merge
database opens cleanly and entries read back at the row level (not just
`COUNT(*)`). If a merge ever returns an integrity error, restore from the
snapshot rather than continuing to operate on the corrupt file.
