"""Bench tooling — scripts that operate on bench/results/ artefacts.

This package is intentionally tiny: it exists so the aggregator can be
imported as ``scripts.bench.aggregate_results`` from tests, while still
being runnable as a standalone CLI (``python scripts/bench/aggregate_results.py``).
"""
