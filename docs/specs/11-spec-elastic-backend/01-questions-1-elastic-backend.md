# Clarifying Questions — Round 1

## Motivation
**Q:** What is the primary motivation for adding Elasticsearch as a backend?
**A:** All of the above — team/multi-user scale, search quality, and cloud-native deployment.

## Flavor
**Q:** Which Elasticsearch flavors should be supported?
**A:** Elasticsearch 9 Serverless Cloud.

## Vector Search
**Q:** How should vector search work in the ES backend?
**A:** Use BBQ (Better Binary Quantization) — `bbq_hnsw` index type, default in ES 9.1+ for dims >= 384. 32x compression, ~95% memory reduction.

## Embeddings
**Q:** Should the ES backend manage its own embeddings or reuse the existing EmbeddingProvider?
**A:** Support both — client-side via EmbeddingProvider (Jina/OpenAI) and server-side via ES Inference API.

## Embedding Phasing
**Q:** Should Unit 1 focus on EmbeddingProvider path and add ES inference later?
**A:** Both from day one — support both embedding paths in the initial implementation.

## Logging
**Q:** Should the ES backend support search_log and feedback_log?
**A:** Yes, full protocol — implement all DistilleryStore methods including logging.

## Research Notes

### ES|QL
ES|QL cannot perform kNN/vector similarity queries. All semantic search must use Query DSL. ES|QL is useful for analytics/reporting but not needed for the storage backend. Decision: use Query DSL for all operations.

### Elastic Marketplace
No plug-and-play skills exist for this use case. The `semantic_text` field type + Inference API is the closest to "configure rather than code" for server-side embedding.

### Python Client
Standard `elasticsearch` 9.x package (`pip install elasticsearch`). The `elasticsearch-serverless` package is deprecated. Async client: `AsyncElasticsearch`.
