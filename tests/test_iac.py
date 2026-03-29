"""Tests for infrastructure-as-code files (Terraform, Docker, GitHub Actions).

These tests validate file existence, structure, and basic correctness
without requiring terraform, docker, or act CLIs.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest
import yaml

# Repo root is two levels above this test file (tests/ -> repo root)
REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Terraform tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTerraform:
    """Validate Terraform configuration files."""

    terraform_dir = REPO_ROOT / "terraform"

    def test_terraform_directory_exists(self) -> None:
        assert self.terraform_dir.is_dir(), "terraform/ directory must exist"

    @pytest.mark.parametrize(
        "filename",
        ["main.tf", "variables.tf", "outputs.tf", "endpoint.tf", "backend.tf", "versions.tf"],
    )
    def test_terraform_required_files_exist(self, filename: str) -> None:
        filepath = self.terraform_dir / filename
        assert filepath.is_file(), f"terraform/{filename} must exist"

    def test_terraform_bootstrap_exists(self) -> None:
        bootstrap_main = self.terraform_dir / "bootstrap" / "main.tf"
        assert bootstrap_main.is_file(), "terraform/bootstrap/main.tf must exist"

    @pytest.mark.parametrize(
        "key",
        ["endpoint_url", "s3_bucket_name", "ecr_repository_url", "lambda_function_name"],
    )
    def test_terraform_outputs_contain_required_keys(self, key: str) -> None:
        outputs_content = (self.terraform_dir / "outputs.tf").read_text()
        assert key in outputs_content, (
            f"outputs.tf must contain '{key}'"
        )

    def test_terraform_variables_contain_endpoint_type(self) -> None:
        variables_content = (self.terraform_dir / "variables.tf").read_text()
        assert "endpoint_type" in variables_content, (
            "variables.tf must contain 'endpoint_type' variable"
        )

    def test_terraform_main_contains_s3_public_access_block(self) -> None:
        main_content = (self.terraform_dir / "main.tf").read_text()
        assert "aws_s3_bucket_public_access_block" in main_content, (
            "main.tf must contain aws_s3_bucket_public_access_block resource"
        )

    def test_terraform_main_contains_lambda_alias(self) -> None:
        main_content = (self.terraform_dir / "main.tf").read_text()
        assert "aws_lambda_alias" in main_content, (
            "main.tf must contain aws_lambda_alias resource"
        )

    def test_terraform_no_hardcoded_secrets(self) -> None:
        """Scan all .tf files for patterns that look like hardcoded secrets."""
        secret_patterns = [
            (r"AKIA[0-9A-Z]{16}", "AWS access key (AKIA...)"),
            (r"sk-[a-zA-Z0-9]{20,}", "Secret key (sk-...)"),
            (r"ghp_[a-zA-Z0-9]{36}", "GitHub personal access token (ghp_...)"),
            (r"ghs_[a-zA-Z0-9]{36}", "GitHub server token (ghs_...)"),
            (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth token (gho_...)"),
        ]
        tf_files = list(self.terraform_dir.rglob("*.tf"))
        assert tf_files, "Expected at least one .tf file"

        for tf_file in tf_files:
            content = tf_file.read_text()
            for pattern, description in secret_patterns:
                assert not re.search(pattern, content), (
                    f"{tf_file.name} contains what looks like a hardcoded secret: {description}"
                )


# ---------------------------------------------------------------------------
# Dockerfile tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDockerfile:
    """Validate Dockerfile and .dockerignore."""

    def test_dockerfile_exists(self) -> None:
        assert (REPO_ROOT / "Dockerfile").is_file(), "Dockerfile must exist at repo root"

    def test_dockerfile_uses_lambda_base_image(self) -> None:
        content = (REPO_ROOT / "Dockerfile").read_text()
        assert "public.ecr.aws/lambda/python" in content, (
            "Dockerfile must use the AWS Lambda Python base image"
        )

    def test_dockerfile_no_dev_dependencies(self) -> None:
        content = (REPO_ROOT / "Dockerfile").read_text()
        assert ".[dev]" not in content, (
            "Dockerfile must not install dev dependencies (.[dev])"
        )

    def test_dockerignore_exists(self) -> None:
        assert (REPO_ROOT / ".dockerignore").is_file(), ".dockerignore must exist at repo root"

    def test_dockerignore_excludes_secrets(self) -> None:
        content = (REPO_ROOT / ".dockerignore").read_text()
        assert ".env" in content, ".dockerignore must exclude .env files"


# ---------------------------------------------------------------------------
# GitHub Actions CD tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeployWorkflow:
    """Validate the GitHub Actions deploy workflow."""

    workflow_path = REPO_ROOT / ".github" / "workflows" / "deploy.yml"

    def test_deploy_workflow_exists(self) -> None:
        assert self.workflow_path.is_file(), ".github/workflows/deploy.yml must exist"

    def test_deploy_workflow_valid_yaml(self) -> None:
        content = self.workflow_path.read_text()
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict), "deploy.yml must parse as a YAML mapping"

    def test_deploy_workflow_has_concurrency(self) -> None:
        content = self.workflow_path.read_text()
        assert "concurrency" in content, "deploy.yml must contain a concurrency group"

    def test_deploy_workflow_has_oidc(self) -> None:
        content = self.workflow_path.read_text()
        assert "id-token: write" in content, (
            "deploy.yml must contain 'id-token: write' permission for OIDC"
        )

    def test_deploy_workflow_has_smoke_test(self) -> None:
        content = self.workflow_path.read_text()
        assert "smoke" in content.lower(), "deploy.yml must contain a smoke test step"

    def test_deploy_workflow_no_hardcoded_aws(self) -> None:
        """Ensure no hardcoded 12-digit AWS account IDs appear in the workflow."""
        content = self.workflow_path.read_text()
        # Match standalone 12-digit numbers (not inside variable references)
        # Exclude lines that are clearly variable references like ${{ vars.AWS_ACCOUNT_ID }}
        for line in content.splitlines():
            # Skip lines that are variable interpolations
            if "${{" in line and "ACCOUNT_ID" in line:
                continue
            match = re.search(r"\b\d{12}\b", line)
            assert match is None, (
                f"deploy.yml contains what looks like a hardcoded AWS account ID: {match.group()}"
            )


# ---------------------------------------------------------------------------
# Smoke test script
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSmokeScript:
    """Validate the smoke test script."""

    script_path = REPO_ROOT / "scripts" / "smoke-test.sh"

    def test_smoke_script_exists(self) -> None:
        assert self.script_path.is_file(), "scripts/smoke-test.sh must exist"

    def test_smoke_script_executable(self) -> None:
        file_stat = os.stat(self.script_path)
        is_executable = bool(file_stat.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        assert is_executable, "scripts/smoke-test.sh must have execute permission"


# ---------------------------------------------------------------------------
# Lambda handler config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLambdaConfig:
    """Validate the Lambda deployment config."""

    config_path = REPO_ROOT / "distillery.lambda.yaml"

    def test_lambda_config_no_hardcoded_secrets(self) -> None:
        """Ensure the Lambda config references env vars, not actual API keys."""
        assert self.config_path.exists(), f"Lambda config not found: {self.config_path}"
        content = self.config_path.read_text()
        secret_patterns = [
            (r"AKIA[0-9A-Z]{16}", "AWS access key"),
            (r"sk-[a-zA-Z0-9]{20,}", "Secret key (sk-...)"),
            (r"ghp_[a-zA-Z0-9]{36}", "GitHub personal access token"),
            (r"jina_[a-zA-Z0-9]{20,}", "Jina API key"),
        ]
        for pattern, description in secret_patterns:
            assert not re.search(pattern, content), (
                f"distillery.lambda.yaml contains what looks like a hardcoded secret: "
                f"{description}"
            )
