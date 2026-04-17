"""Tests for .grype.yaml — supply chain vulnerability scanning configuration.

Covers:
  - File is valid YAML
  - Required top-level fields present (ignore, fail-on-severity, output)
  - Each ignore entry has required fields (vulnerability, reason)
  - No duplicate CVE entries in the ignore list
  - fail-on-severity is set to an appropriate level
  - CVEs added in PR #272 / v0.4.0 are present with non-empty reasons
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent
GRYPE_YAML_PATH = REPO_ROOT / ".grype.yaml"


def load_grype_config() -> dict[str, Any]:
    """Load and parse .grype.yaml from the repository root."""
    return yaml.safe_load(GRYPE_YAML_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# File-level tests
# ---------------------------------------------------------------------------


class TestGrypeYamlFile:
    def test_grype_yaml_exists(self) -> None:
        """.grype.yaml must exist at the repository root."""
        assert GRYPE_YAML_PATH.exists(), f".grype.yaml not found at {GRYPE_YAML_PATH}"

    def test_grype_yaml_is_valid_yaml(self) -> None:
        """.grype.yaml must be parseable as valid YAML."""
        content = GRYPE_YAML_PATH.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict), ".grype.yaml must parse to a YAML mapping"

    def test_grype_yaml_is_non_empty(self) -> None:
        """.grype.yaml must not be empty."""
        config = load_grype_config()
        assert len(config) > 0


# ---------------------------------------------------------------------------
# Required top-level fields
# ---------------------------------------------------------------------------


class TestGrypeTopLevelFields:
    def test_ignore_field_present(self) -> None:
        """ignore field must be present."""
        config = load_grype_config()
        assert "ignore" in config, "Missing 'ignore' key in .grype.yaml"

    def test_ignore_is_list(self) -> None:
        """ignore must be a list."""
        config = load_grype_config()
        assert isinstance(config["ignore"], list)

    def test_fail_on_severity_present(self) -> None:
        """fail-on-severity field must be present."""
        config = load_grype_config()
        assert "fail-on-severity" in config, "Missing 'fail-on-severity' in .grype.yaml"

    def test_fail_on_severity_is_high(self) -> None:
        """fail-on-severity must be set to 'high' per project standards."""
        config = load_grype_config()
        assert config["fail-on-severity"] == "high", (
            f"Expected fail-on-severity='high', got {config['fail-on-severity']!r}"
        )

    def test_output_field_present(self) -> None:
        """output field must be present."""
        config = load_grype_config()
        assert "output" in config, "Missing 'output' field in .grype.yaml"

    def test_output_is_table(self) -> None:
        """output must be 'table' for local scans."""
        config = load_grype_config()
        assert config["output"] == "table"


# ---------------------------------------------------------------------------
# Ignore entry validation
# ---------------------------------------------------------------------------


class TestGrypeIgnoreEntries:
    def _get_ignore_entries(self) -> list[dict[str, Any]]:
        config = load_grype_config()
        return config.get("ignore", [])

    def test_every_ignore_entry_has_vulnerability(self) -> None:
        """Every ignore entry must have a 'vulnerability' field."""
        entries = self._get_ignore_entries()
        assert len(entries) > 0, "No ignore entries found"
        for i, entry in enumerate(entries):
            assert "vulnerability" in entry, (
                f"ignore entry {i} missing 'vulnerability' field: {entry}"
            )

    def test_every_ignore_entry_has_reason(self) -> None:
        """Every ignore entry must have a 'reason' field explaining why it is safe to ignore."""
        entries = self._get_ignore_entries()
        for entry in entries:
            cve = entry.get("vulnerability", "<unknown>")
            assert "reason" in entry, f"Ignore entry for {cve} missing 'reason' field"

    def test_every_reason_is_non_empty(self) -> None:
        """Every reason field must be a non-empty string."""
        entries = self._get_ignore_entries()
        for entry in entries:
            cve = entry.get("vulnerability", "<unknown>")
            reason = entry.get("reason", "")
            assert isinstance(reason, str), f"reason for {cve} must be a string"
            assert len(reason.strip()) > 0, f"reason for {cve} must not be empty"

    def test_every_vulnerability_is_cve_formatted(self) -> None:
        """Every vulnerability ID must follow CVE-YYYY-NNNNN format."""
        import re

        entries = self._get_ignore_entries()
        pattern = re.compile(r"^CVE-\d{4}-\d+$")
        for entry in entries:
            vuln = entry.get("vulnerability", "")
            assert pattern.match(vuln), (
                f"Vulnerability ID '{vuln}' does not match CVE-YYYY-NNNNN format"
            )


# ---------------------------------------------------------------------------
# Duplicate CVE detection
# ---------------------------------------------------------------------------


class TestGrypeNoDuplicates:
    def test_no_duplicate_cve_entries(self) -> None:
        """The ignore list must not contain duplicate CVE IDs.

        Duplicates confuse grype and indicate a copy-paste error during maintenance.
        CVE-2026-31790 was introduced as a duplicate in PR v0.4.0 and must be caught.
        """
        config = load_grype_config()
        entries = config.get("ignore", [])
        seen: dict[str, int] = {}
        duplicates: list[str] = []
        for i, entry in enumerate(entries):
            vuln = entry.get("vulnerability", "")
            if vuln in seen:
                duplicates.append(
                    f"{vuln} appears at index {seen[vuln]} and {i}"
                )
            else:
                seen[vuln] = i
        assert not duplicates, (
            "Duplicate CVE entries found in .grype.yaml ignore list:\n"
            + "\n".join(f"  - {d}" for d in duplicates)
        )

    def test_cve_2026_31790_appears_exactly_once(self) -> None:
        """CVE-2026-31790 must appear exactly once in the ignore list.

        Regression test: this CVE was duplicated in the v0.4.0 PR when the
        openssl entry was added to the new Go-CVE block and also retained
        in the existing CPython block.
        """
        config = load_grype_config()
        entries = config.get("ignore", [])
        count = sum(
            1 for e in entries if e.get("vulnerability") == "CVE-2026-31790"
        )
        assert count == 1, (
            f"CVE-2026-31790 appears {count} times in .grype.yaml ignore list "
            f"(expected exactly 1)"
        )


# ---------------------------------------------------------------------------
# v0.4.0 CVE additions
# ---------------------------------------------------------------------------

# CVEs added in the v0.4.0 PR (Go stdlib block + Python 3.13 CVE-2026-6100).
GO_STDLIB_CVES_V040 = [
    "CVE-2025-68121",
    "CVE-2026-25679",
    "CVE-2025-61729",
    "CVE-2026-27140",
    "CVE-2026-32283",
    "CVE-2026-32280",
    "CVE-2026-32281",
    "CVE-2025-58187",
    "CVE-2025-61731",
    "CVE-2025-61732",
    "CVE-2025-58188",
]

PYTHON_CVES_V040 = [
    "CVE-2026-6100",
]


class TestGrypev040Additions:
    def _get_cve_set(self) -> set[str]:
        config = load_grype_config()
        return {e.get("vulnerability", "") for e in config.get("ignore", [])}

    def test_go_stdlib_cves_present(self) -> None:
        """All Go stdlib CVEs added in v0.4.0 must be present in the ignore list."""
        cve_set = self._get_cve_set()
        for cve in GO_STDLIB_CVES_V040:
            assert cve in cve_set, f"Go stdlib CVE {cve} (v0.4.0) missing from ignore list"

    def test_python_cves_present(self) -> None:
        """Python 3.13 CVEs added in v0.4.0 must be present in the ignore list."""
        cve_set = self._get_cve_set()
        for cve in PYTHON_CVES_V040:
            assert cve in cve_set, f"Python CVE {cve} (v0.4.0) missing from ignore list"

    def test_go_cve_reasons_mention_go_stdlib(self) -> None:
        """Go stdlib CVE reasons must mention 'Go' to distinguish from other CVEs."""
        config = load_grype_config()
        entries = {e["vulnerability"]: e["reason"] for e in config.get("ignore", [])}
        for cve in GO_STDLIB_CVES_V040:
            reason = entries.get(cve, "")
            assert "Go" in reason or "go" in reason.lower(), (
                f"CVE {cve} reason does not mention 'Go': {reason!r}"
            )

    def test_python_cve_reason_mentions_cpython(self) -> None:
        """Python CVE-2026-6100 reason must mention CPython."""
        config = load_grype_config()
        entries = {e["vulnerability"]: e["reason"] for e in config.get("ignore", [])}
        cve = "CVE-2026-6100"
        reason = entries.get(cve, "")
        assert "CPython" in reason or "Python" in reason, (
            f"CVE {cve} reason does not mention CPython/Python: {reason!r}"
        )

    def test_openssl_cve_2026_31790_reason_mentions_tls(self) -> None:
        """CVE-2026-31790 reason must mention TLS (it is a TLS cert verification issue)."""
        config = load_grype_config()
        entries = {e["vulnerability"]: e["reason"] for e in config.get("ignore", [])}
        cve = "CVE-2026-31790"
        reason = entries.get(cve, "")
        assert "TLS" in reason or "tls" in reason.lower() or "certificate" in reason.lower(), (
            f"CVE {cve} reason does not mention TLS/certificate: {reason!r}"
        )