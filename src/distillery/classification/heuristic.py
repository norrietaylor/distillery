"""Heuristic classifier using embedding centroids.

This module provides :class:`HeuristicClassifier`, which classifies entries
by computing cosine similarity between entry embeddings and per-type centroid
vectors.  Unlike :class:`~distillery.classification.engine.ClassificationEngine`,
this classifier does not require any LLM API calls -- it relies solely on the
embedding provider and existing stored entries.

The centroid for each entry type is the L2-normalised mean of all embeddings
for active entries of that type.  Types with fewer than
:data:`MIN_ENTRIES_PER_TYPE` entries are excluded (insufficient data).
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from distillery.models import EntryStatus, EntryType

from .models import ClassificationResult

if TYPE_CHECKING:
    from distillery.embedding.protocol import EmbeddingProvider
    from distillery.models import Entry
    from distillery.store.protocol import DistilleryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_ENTRIES_PER_TYPE: int = 3
"""Minimum number of active entries a type must have to compute a centroid."""

SIMILARITY_THRESHOLD: float = 0.5
"""Minimum cosine similarity to a centroid for a positive classification."""


# ---------------------------------------------------------------------------
# Cosine similarity helper
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute the cosine similarity between two vectors.

    Both vectors must have the same length.  If either vector has zero
    magnitude the function returns ``0.0``.

    Args:
        a: First embedding vector.
        b: Second embedding vector.

    Returns:
        Cosine similarity in ``[-1.0, 1.0]``.
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# HeuristicClassifier
# ---------------------------------------------------------------------------


class HeuristicClassifier:
    """Classify entries by cosine similarity to per-type embedding centroids.

    The classifier follows three steps:

    1. Compute centroids: for each entry type with at least
       :data:`MIN_ENTRIES_PER_TYPE` active entries, average the embeddings
       to produce a centroid vector.
    2. Embed the candidate entry.
    3. Compare the candidate embedding to each centroid via cosine similarity.
       If the best similarity meets or exceeds :data:`SIMILARITY_THRESHOLD`,
       the entry is classified as that type.  Otherwise the entry is sent to
       review.

    This class is stateless -- it does not cache centroids between calls.
    Callers that need to classify many entries in a batch should call
    :meth:`compute_centroids` once and then :meth:`classify_entry` for each.

    Example::

        classifier = HeuristicClassifier()
        result = await classifier.classify(entry, store, embedding_provider)
    """

    async def classify(
        self,
        entry: Entry,
        store: DistilleryStore,
        embedding_provider: EmbeddingProvider,
    ) -> ClassificationResult:
        """Classify a single entry using embedding centroids.

        Computes centroids from the store, embeds the entry, and returns a
        :class:`~distillery.classification.models.ClassificationResult`.

        Args:
            entry: The entry to classify.
            store: Storage backend for querying existing entries.
            embedding_provider: Provider for generating embeddings.

        Returns:
            A classification result with the predicted type and confidence.
        """
        centroids = await self.compute_centroids(store, embedding_provider)

        if not centroids:
            logger.info("HeuristicClassifier: no centroids available, sending to review")
            return ClassificationResult(
                entry_type=EntryType.INBOX,
                confidence=0.0,
                status=EntryStatus.PENDING_REVIEW,
                reasoning="No entry types have sufficient data for heuristic classification.",
                suggested_tags=[],
                suggested_project=None,
            )

        entry_embedding = embedding_provider.embed(entry.content)
        best_type, best_similarity = self.classify_entry(entry_embedding, centroids)

        if best_type is not None:
            return ClassificationResult(
                entry_type=EntryType(best_type),
                confidence=best_similarity,
                status=EntryStatus.ACTIVE,
                reasoning=(
                    f"Heuristic classification: best centroid match is "
                    f"{best_type!r} with similarity {best_similarity:.3f}."
                ),
                suggested_tags=[],
                suggested_project=None,
            )

        return ClassificationResult(
            entry_type=EntryType.INBOX,
            confidence=best_similarity,
            status=EntryStatus.PENDING_REVIEW,
            reasoning=(
                f"Heuristic classification: no centroid exceeded threshold "
                f"{SIMILARITY_THRESHOLD}; best similarity was {best_similarity:.3f}."
            ),
            suggested_tags=[],
            suggested_project=None,
        )

    async def compute_centroids(
        self,
        store: DistilleryStore,
        embedding_provider: EmbeddingProvider,
    ) -> dict[str, list[float]]:
        """Compute centroid embeddings for each entry type.

        Queries the store for active entries grouped by type.  Types with
        fewer than :data:`MIN_ENTRIES_PER_TYPE` entries are excluded.  For
        qualifying types, the centroid is the element-wise mean of all entry
        embeddings, L2-normalised.

        Args:
            store: Storage backend for querying existing entries.
            embedding_provider: Provider for generating embeddings.

        Returns:
            A dict mapping entry type string values to their centroid vectors.
        """
        centroids: dict[str, list[float]] = {}

        for entry_type in EntryType:
            if entry_type == EntryType.INBOX:
                # Inbox entries are unclassified -- skip.
                continue

            # Cap at 1000 most recent entries per type. For typical KBs (<10k
            # entries) this covers all entries; for larger corpora the centroid
            # is biased toward recent content, which is acceptable for v1.
            result = await store.list_entries(
                filters={"entry_type": entry_type.value, "status": "active"},
                limit=1000,
                offset=0,
            )
            # list_entries without group_by/output always returns list[Entry].
            if not isinstance(result, list):
                logger.warning(
                    "HeuristicClassifier: unexpected result type from list_entries: %s",
                    type(result).__name__,
                )
                continue
            entries: list[Entry] = result

            if len(entries) < MIN_ENTRIES_PER_TYPE:
                logger.debug(
                    "HeuristicClassifier: skipping type %r (%d entries, need %d)",
                    entry_type.value,
                    len(entries),
                    MIN_ENTRIES_PER_TYPE,
                )
                continue

            # Embed all entry contents.
            texts = [e.content for e in entries]
            embeddings = embedding_provider.embed_batch(texts)

            # Compute element-wise mean.
            dims = len(embeddings[0])
            centroid = [0.0] * dims
            for emb in embeddings:
                for i in range(dims):
                    centroid[i] += emb[i]
            count = len(embeddings)
            centroid = [c / count for c in centroid]

            # L2-normalise the centroid.
            magnitude = math.sqrt(sum(c * c for c in centroid))
            if magnitude > 0.0:
                centroid = [c / magnitude for c in centroid]

            centroids[entry_type.value] = centroid
            logger.debug(
                "HeuristicClassifier: computed centroid for type %r from %d entries",
                entry_type.value,
                count,
            )

        return centroids

    def classify_entry(
        self,
        entry_embedding: list[float],
        centroids: dict[str, list[float]],
    ) -> tuple[str | None, float]:
        """Compare an embedding against centroids and return the best match.

        Args:
            entry_embedding: The embedding vector of the entry to classify.
            centroids: A dict mapping entry type values to centroid vectors
                (as returned by :meth:`compute_centroids`).

        Returns:
            A ``(best_type, similarity)`` tuple.  ``best_type`` is the entry
            type string if the best similarity meets or exceeds
            :data:`SIMILARITY_THRESHOLD`, otherwise ``None``.
        """
        best_type: str | None = None
        best_similarity: float = -1.0

        for type_name, centroid in centroids.items():
            sim = cosine_similarity(entry_embedding, centroid)
            if sim > best_similarity:
                best_similarity = sim
                best_type = type_name

        if best_similarity >= SIMILARITY_THRESHOLD:
            return (best_type, best_similarity)

        return (None, best_similarity)

    async def classify_batch(
        self,
        entries: list[Entry],
        store: DistilleryStore,
        embedding_provider: EmbeddingProvider,
    ) -> list[ClassificationResult]:
        """Classify a batch of entries, computing centroids only once.

        This is more efficient than calling :meth:`classify` per entry because
        centroid computation (which queries the store for all active entries) is
        done once and reused for the entire batch.

        Args:
            entries: The entries to classify.
            store: Storage backend for querying existing entries.
            embedding_provider: Provider for generating embeddings.

        Returns:
            A list of :class:`~distillery.classification.models.ClassificationResult`
            objects in the same order as *entries*.
        """
        centroids = await self.compute_centroids(store, embedding_provider)

        results: list[ClassificationResult] = []
        for entry in entries:
            if not centroids:
                results.append(
                    ClassificationResult(
                        entry_type=EntryType.INBOX,
                        confidence=0.0,
                        status=EntryStatus.PENDING_REVIEW,
                        reasoning="No entry types have sufficient data for heuristic classification.",
                        suggested_tags=[],
                        suggested_project=None,
                    )
                )
                continue

            entry_embedding = embedding_provider.embed(entry.content)
            best_type, best_similarity = self.classify_entry(entry_embedding, centroids)

            if best_type is not None:
                results.append(
                    ClassificationResult(
                        entry_type=EntryType(best_type),
                        confidence=best_similarity,
                        status=EntryStatus.ACTIVE,
                        reasoning=(
                            f"Heuristic classification: best centroid match is "
                            f"{best_type!r} with similarity {best_similarity:.3f}."
                        ),
                        suggested_tags=[],
                        suggested_project=None,
                    )
                )
            else:
                results.append(
                    ClassificationResult(
                        entry_type=EntryType.INBOX,
                        confidence=best_similarity,
                        status=EntryStatus.PENDING_REVIEW,
                        reasoning=(
                            f"Heuristic classification: no centroid exceeded threshold "
                            f"{SIMILARITY_THRESHOLD}; best similarity was {best_similarity:.3f}."
                        ),
                        suggested_tags=[],
                        suggested_project=None,
                    )
                )

        return results
