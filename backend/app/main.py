"""FastAPI application entry point.

Stage 0 scaffold: only the health endpoint used by smoke tests and E2E
readiness checks exists. Feature routers arrive with their stages.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Public health payload."""

    status: str


def create_api_v1_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["meta"])

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return router


def create_app() -> FastAPI:
    app = FastAPI(title="BaseFit API", version="0.1.0")
    app.include_router(create_api_v1_router())
    return app


app = create_app()
