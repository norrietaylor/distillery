"""Gateway configuration — loaded from gateway.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class UserConfig:
    token: str
    db_path: str
    project: str = ""


@dataclass
class EmbeddingConfig:
    provider: str = "jina"
    model: str = "jina-embeddings-v3"
    dimensions: int = 1024
    api_key_env: str = "JINA_API_KEY"


@dataclass
class GatewayConfig:
    users: list[UserConfig] = field(default_factory=list)
    anthropic_api_key_env: str = "ANTHROPIC_API_KEY"
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    require_summarization: bool = True
    rate_limit_per_minute: int = 60
    host: str = "0.0.0.0"
    port: int = 8080

    # Resolved at load time — not from YAML
    _anthropic_api_key: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._anthropic_api_key = os.environ.get(self.anthropic_api_key_env)
        if self.require_summarization and not self._anthropic_api_key:
            raise ValueError(
                f"ANTHROPIC_API_KEY (env: {self.anthropic_api_key_env}) is required "
                "when require_summarization=true. Set it or add require_summarization: false "
                "to gateway.yaml."
            )

    @property
    def anthropic_api_key(self) -> str | None:
        return self._anthropic_api_key

    @classmethod
    def load(cls, path: Path) -> GatewayConfig:
        with path.open() as f:
            raw = yaml.safe_load(f)

        users = [
            UserConfig(
                token=u["token"],
                db_path=u["db_path"],
                project=u.get("project", ""),
            )
            for u in raw.get("users", [])
        ]

        embedding_raw = raw.get("embedding", {})
        embedding = EmbeddingConfig(
            provider=embedding_raw.get("provider", "jina"),
            model=embedding_raw.get("model", "jina-embeddings-v3"),
            dimensions=int(embedding_raw.get("dimensions", 1024)),
            api_key_env=embedding_raw.get("api_key_env", "JINA_API_KEY"),
        )

        return cls(
            users=users,
            anthropic_api_key_env=raw.get("anthropic_api_key_env", "ANTHROPIC_API_KEY"),
            embedding=embedding,
            require_summarization=raw.get("require_summarization", True),
            rate_limit_per_minute=int(raw.get("rate_limit_per_minute", 60)),
            host=raw.get("host", "0.0.0.0"),
            port=int(raw.get("port", 8080)),
        )

    def get_user(self, token: str) -> UserConfig | None:
        """Return the UserConfig for a given bearer token, or None if not found."""
        for user in self.users:
            if user.token == token:
                return user
        return None
