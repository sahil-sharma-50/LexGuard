"""GET-only API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from lexguard.api.projections import RepositoryReadStore
from lexguard.api.schemas import ReadStore
from lexguard.api.sse import encode_events


def build_router(store: ReadStore) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/status")
    def status() -> object:
        payload = store.status()
        # RepositoryReadStore's status payload already contains the health
        # result, so this remains one database health query per request.
        if isinstance(store, RepositoryReadStore):
            ready = payload.components.get("database") == "healthy"
        else:
            is_ready = getattr(store, "is_ready", None)
            ready = not callable(is_ready) or bool(is_ready())
        if not ready:
            return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))
        return payload

    @router.get("/cases")
    def cases(
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
    ) -> object:
        return store.list_cases(offset, limit)

    @router.get("/cases/{case_id}")
    def case_detail(case_id: UUID) -> object:
        result = store.get_case(case_id)
        if result is None:
            raise HTTPException(status_code=404, detail="case not found")
        return result

    @router.get("/performance")
    def performance() -> object:
        return store.get_performance()

    @router.get("/research/summary")
    def research_summary() -> object:
        return store.get_research()

    @router.get("/events")
    def events(request: Request) -> StreamingResponse:
        raw_last_id = request.headers.get("last-event-id", "0")
        try:
            last_id = max(0, int(raw_last_id))
        except ValueError:
            last_id = 0
        return StreamingResponse(
            encode_events(store.get_events(last_id)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
