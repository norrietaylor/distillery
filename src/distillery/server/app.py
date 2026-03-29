"""Distillery HTTP Gateway — FastAPI application factory."""

from __future__ import annotations

import importlib.metadata
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

from distillery.embedding.jina import JinaEmbeddingProvider
from distillery.store.duckdb import DuckDBStore

from .bookmark import BookmarkRequest, BookmarkService
from .config import GatewayConfig, UserConfig

# ── App factory ───────────────────────────────────────────────────────────────


def create_app(gateway_config: GatewayConfig) -> FastAPI:
    app = FastAPI(
        title="Distillery HTTP Gateway",
        version=_version(),
        docs_url="/docs",
    )

    # Allow browser extension origins
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(chrome-extension|moz-extension|safari-web-extension)://.*",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Store gateway config on app state for dependency injection
    app.state.gateway_config = gateway_config

    # Register routes
    app.include_router(_health_router(gateway_config))
    app.include_router(_api_router())

    return app


# ── Auth dependency ───────────────────────────────────────────────────────────


async def _get_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> UserConfig:
    gateway_config: GatewayConfig = request.app.state.gateway_config

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    user = gateway_config.get_user(token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    return user


AuthUser = Annotated[UserConfig, Depends(_get_user)]


# ── Health router ─────────────────────────────────────────────────────────────


def _health_router(gateway_config: GatewayConfig) -> Any:
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok" if gateway_config.anthropic_api_key is not None else "degraded",
            "version": _version(),
            "summarization": gateway_config.anthropic_api_key is not None,
        }

    return router


# ── API router ────────────────────────────────────────────────────────────────


def _api_router() -> Any:
    from fastapi import APIRouter

    router = APIRouter(prefix="/api")

    # ── Pydantic models ────────────────────────────────────────────────────────

    class BookmarkPayload(BaseModel):
        url: HttpUrl
        tags: list[str] = []
        project: str = ""
        force: bool = False

    class WatchPayload(BaseModel):
        url: HttpUrl
        type: str | None = None  # auto-detect if omitted
        interval: str = "6h"
        tags: list[str] = []
        project: str = ""

    # ── POST /api/bookmark ────────────────────────────────────────────────────

    @router.post("/bookmark", status_code=200)
    async def bookmark(
        payload: BookmarkPayload,
        request: Request,
        user: AuthUser,
    ) -> dict[str, Any]:
        gateway_config: GatewayConfig = request.app.state.gateway_config

        if not gateway_config.anthropic_api_key:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    "Server is missing Anthropic API key. "
                    "Set the ANTHROPIC_API_KEY environment variable."
                ),
            )

        store = await _get_store(user, gateway_config)

        service = BookmarkService(
            store=store,
            anthropic_api_key=gateway_config.anthropic_api_key,
        )

        req = BookmarkRequest(
            url=str(payload.url),
            tags=payload.tags,
            project=payload.project or user.project,
            author=f"user/{user.project}" if user.project else "user/anonymous",
            force=payload.force,
        )

        try:
            result = await service.bookmark(req)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

        if result.duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "duplicate": True,
                    "existing_id": result.existing_id,
                    "similarity": result.similarity,
                    "force": False,
                },
            )

        return {
            "entry_id": result.entry_id,
            "summary": result.summary,
            "tags": result.tags,
            "duplicate": False,
        }

    # ── POST /api/watch ────────────────────────────────────────────────────────

    @router.post("/watch", status_code=201)
    async def watch(payload: WatchPayload, user: AuthUser) -> dict[str, Any]:
        # Placeholder — full implementation in Spec 05
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Watch skill not yet implemented. Coming in Spec 05.",
        )

    # ── GET /api/status ────────────────────────────────────────────────────────

    @router.get("/status")
    async def db_status(request: Request, user: AuthUser) -> dict[str, Any]:
        gateway_config: GatewayConfig = request.app.state.gateway_config
        store = await _get_store(user, gateway_config)
        entries = await store.list_entries(filters=None, limit=None, offset=0)
        return {"entry_count": len(entries), "db_path": user.db_path}

    return router


# ── Store factory ─────────────────────────────────────────────────────────────


async def _get_store(user: UserConfig, gateway_config: GatewayConfig) -> DuckDBStore:
    """Return an initialised DuckDBStore for the given user."""
    import os

    embedding_key = os.environ.get(gateway_config.embedding.api_key_env, "")
    embedding_provider = JinaEmbeddingProvider(
        api_key=embedding_key,
        model=gateway_config.embedding.model,
        dimensions=gateway_config.embedding.dimensions,
    )

    store = DuckDBStore(
        db_path=user.db_path,
        embedding_provider=embedding_provider,
    )
    await store.initialize()

    return store


# ── Helpers ───────────────────────────────────────────────────────────────────


def _version() -> str:
    try:
        return importlib.metadata.version("distillery")
    except importlib.metadata.PackageNotFoundError:
        return "dev"
