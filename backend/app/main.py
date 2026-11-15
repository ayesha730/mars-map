"""
AresPath FastAPI application.

Mounts API v1 router and installs global exception handlers that enforce
the PRD standard error envelope:
  { status, error: { code, message, details }, request_id }
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import API_V1_STR, PROJECT_NAME, VERSION
from app.models.schemas import ErrorResponse, ErrorDetail

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=PROJECT_NAME,
    version=VERSION,
    description=(
        "AresPath — NASA Space Apps Challenge 2026 Mars surface routing API.\n\n"
        "**Coordinate convention**: Mars, planetocentric latitude, "
        "positive-east longitude, −180..180°.\n\n"
        "**Display space**: `arespath_display_v1` — X = East (m), Y = North (m), "
        "region-specific projection."
    ),
    contact={
        "name": "AresPath Team",
        "url": "https://github.com/your-org/arespath",
    },
    license_info={"name": "MIT"},
    openapi_tags=[
        {"name": "Health",  "description": "Service liveness and planetary datum"},
        {"name": "Routes",  "description": "Mars surface route computation"},
        {"name": "Regions", "description": "Region and terrain metadata"},
        {"name": "Layers",  "description": "Terrain and map layer catalogue and metadata"},
    ],
)
# ---------------------------------------------------------------------------
# CORS — allow the local Next.js frontend to access the API
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ---------------------------------------------------------------------------
# Global exception handlers — PRD standard error envelope
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Wraps FastAPI/Pydantic validation errors in the PRD standard error
    envelope so the frontend always receives the same shape.
    """
    request_id = str(uuid.uuid4())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="Request validation failed.",
                details=exc.errors(),
            ),
            request_id=request_id,
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    request_id = str(uuid.uuid4())
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected server error occurred.",
                details=str(exc),
            ),
            request_id=request_id,
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(api_router, prefix=API_V1_STR)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health"])
async def root():
    return {
        "message": "Welcome to AresPath API",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "version": VERSION,
    }
