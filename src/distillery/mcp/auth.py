"""GitHub OAuth authentication for the Distillery MCP HTTP transport.

Provides :func:`build_github_auth` which reads OAuth credentials from
environment variables (names configured in ``distillery.yaml``) and returns
a configured ``GitHubProvider`` instance for FastMCP.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

from fastmcp.server.auth.providers.github import GitHubProvider

from distillery.config import DistilleryConfig

logger = logging.getLogger(__name__)


def build_github_auth(config: DistilleryConfig) -> GitHubProvider:
    """Build a :class:`~fastmcp.server.auth.providers.github.GitHubProvider`.

    Reads the OAuth client ID and secret from the environment variable names
    specified in ``config.server.auth``.

    Args:
        config: Distillery configuration with ``server.auth`` populated.

    Returns:
        A configured :class:`GitHubProvider` instance.

    Raises:
        ValueError: If either the client ID or client secret environment
            variable is missing or empty.
    """
    auth = config.server.auth
    client_id = os.environ.get(auth.client_id_env, "").strip()
    client_secret = os.environ.get(auth.client_secret_env, "").strip()

    if not client_id:
        raise ValueError(
            f"GitHub OAuth client ID env var {auth.client_id_env!r} is not set or empty. "
            "Set the environment variable before starting the server."
        )

    if not client_secret:
        raise ValueError(
            f"GitHub OAuth client secret env var {auth.client_secret_env!r} is not set or empty. "
            "Set the environment variable before starting the server."
        )

    base_url = os.environ.get("DISTILLERY_BASE_URL", "").strip()
    if not base_url:
        raise ValueError(
            "DISTILLERY_BASE_URL env var is required when server.auth.provider is 'github'. "
            "Set it to the publicly accessible URL of the server "
            "(e.g. 'https://distillery.example.com')."
        )
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            f"DISTILLERY_BASE_URL must be a valid absolute http(s) URL, got: {base_url!r}. "
            "Example: 'https://distillery.example.com'."
        )

    # Log that auth is being configured, but NEVER log secret values.
    logger.info(
        "Configuring GitHub OAuth (client_id_env=%s, base_url=%s)",
        auth.client_id_env,
        base_url,
    )

    return GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
    )
