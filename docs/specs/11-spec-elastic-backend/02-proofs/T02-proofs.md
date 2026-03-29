# T02 Proof Summary: Semantic Search, Similarity, and Dual Embedding

## Task

Implement vector search operations with kNN + BBQ and support both client-side
and server-side embedding.

## Proof Artifacts

| # | Type | File | Status |
|---|------|------|--------|
| 1 | test | T02-01-test.txt | PASS |
| 2 | test | T02-02-test.txt | PASS |
| 3 | cli  | T02-03-cli.txt  | PASS |

## Summary

- **30 search/filter/similarity tests** pass covering all filter keys (entry_type,
  author, project, tags, status, date_from, date_to), score conversion, find_similar
  threshold enforcement, and list_entries pagination.
- **8 embedding mode tests** pass covering client, server, and auto mode selection,
  including semantic_text mapping generation.
- **mypy --strict** passes with zero errors on the implementation file.
- Total: **64 tests** in test_elasticsearch_store.py (26 T01 + 38 T02), all passing.

## Implementation Files

- `src/distillery/store/elasticsearch.py` -- search(), find_similar(), list_entries(),
  _build_filter_clauses(), _convert_es_score(), _detect_inference_endpoint(),
  server/auto embedding mode support
- `tests/test_elasticsearch_store.py` -- 38 new tests across 6 test classes
