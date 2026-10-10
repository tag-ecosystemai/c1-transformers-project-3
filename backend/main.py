from fastapi import FastAPI
from fastapi.middleware.cors import (
    CORSMiddleware,
)

from backend.api import (
    routes_agent,
    routes_briefing,
    routes_inventory,
    routes_predictions,
    routes_shipments,
)
from backend.config import settings


def get_allowed_origins() -> list:
    """
    Return configured frontend origins.

    FRONTEND_URL may contain one origin or a comma-separated list.
    This supports local development and the deployed frontend
    without allowing arbitrary origins.
    """
    origins = [
        origin.strip().rstrip("/")
        for origin in settings.frontend_url.split(",")
        if origin.strip()
    ]

    if not origins:
        raise RuntimeError(
            "FRONTEND_URL must contain at least one allowed origin."
        )

    return origins


app = FastAPI(
    title=(
        "Supply-Chain Disruption Agent API"
    ),
    description=(
        "Risk prediction, operational evidence retrieval, "
        "and AI investigation orchestration layer"
    ),
    version="1.1.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=[
        "*",
    ],
    allow_headers=[
        "*",
    ],
)


app.include_router(
    routes_shipments.router
)

app.include_router(
    routes_predictions.router
)

app.include_router(
    routes_agent.router
)

app.include_router(
    routes_briefing.router
)

app.include_router(
    routes_inventory.router
)


@app.get(
    "/health",
    tags=["Health"],
)
def health_check():
    """
    Report backend-service availability.
    """
    return {
        "status": "healthy",
        "service": (
            "Backend Orchestration"
        ),
    }