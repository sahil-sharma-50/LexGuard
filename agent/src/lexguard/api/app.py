"""FastAPI application exposing only read projections."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lexguard.adapters.repository import CaseRepository
from lexguard.api.operator import (
    BrokerFactory,
    build_operator_router,
    default_broker_factory,
)
from lexguard.api.projections import RepositoryReadStore
from lexguard.api.routes import build_router
from lexguard.api.schemas import ReadStore


def create_app(
    store: ReadStore | None = None,
    *,
    repository: CaseRepository | None = None,
    database_url: str | None = None,
    environment: str | None = None,
    broker_factory: BrokerFactory | None = None,
) -> FastAPI:
    """Build the read + stop-only-control application from the durable ledger."""

    configured_environment = environment or os.getenv("LEXGUARD_ENVIRONMENT")
    selected_environment: Literal["development", "competition"] = (
        "competition" if configured_environment == "competition" else "development"
    )
    selected_repository = repository or CaseRepository(
        database_url
        or os.getenv("DATABASE_URL")
        or "postgresql+psycopg://localhost/lexguard"
    )
    selected_store = store or RepositoryReadStore(
        selected_repository,
        environment=selected_environment,
    )
    app = FastAPI(title="Lexguard Read API", version="0.1.0")
    configured_origin = os.getenv("LEXGUARD_ALLOWED_ORIGIN")
    if selected_environment == "development":
        allowed_origins = sorted(
            {
                configured_origin or "http://localhost:3000",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            }
        )
    else:
        # Competition allows only the explicitly deployed frontend origin. A
        # missing origin is an intentional deny-all CORS configuration.
        allowed_origins = [configured_origin] if configured_origin else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        # POST exists only on the stop-only operator control routes.
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type", "Last-Event-ID", "X-Operator-Token"],
    )
    app.state.read_store = selected_store
    app.include_router(build_router(selected_store))
    app.include_router(
        build_operator_router(
            selected_repository,
            broker_factory=broker_factory or default_broker_factory,
        )
    )
    return app
