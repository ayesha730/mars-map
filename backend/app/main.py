"""
AresPath FastAPI application.

Mounts API v1 router and installs global exception handlers that enforce
the PRD standard error envelope:
  { status, error: { code, message, details }, request_id }
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Dict, Mapping
import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import API_V1_STR, PROJECT_NAME, VERSION, JEZERO_DEM_PATH
from app.models.schemas import ErrorResponse, ErrorDetail
from app.scientific.dem.service import RegionalDEM
from app.scientific.dem.transformer import DEMTransformer


# ---------------------------------------------------------------------------
# Lifespan: DEM resource initialization and shutdown cleanup
# ---------------------------------------------------------------------------

def init_regional_dems() -> Dict[str, RegionalDEM]:
    """
    Initializes RegionalDEM instances for configured supported regions.
    Only returns when all available configured resources initialize cleanly.
    If an initialization failure occurs, all previously opened resources
    are immediately closed and the error is propagated.
    """
    opened: Dict[str, RegionalDEM] = {}
    try:
        # Load Jezero CTX DEM if present on disk
        if JEZERO_DEM_PATH.exists():
            tf = DEMTransformer.from_file(JEZERO_DEM_PATH)
            opened["jezero_crater"] = RegionalDEM(region_id="jezero_crater", transformer=tf)
        return opened
    except Exception as exc:
        # Clean up any opened resources before propagating failure
        for entry in opened.values():
            if entry.transformer and not entry.transformer.is_closed:
                try:
                    entry.transformer.close()
                except Exception:
                    pass
        raise RuntimeError(f"Failed to initialize regional DEM resources: {exc}") from exc


def close_regional_dems(dems: Mapping[str, RegionalDEM]) -> None:
    """
    Safely closes all owned DEM transformers on application shutdown.
    Handles cleanup failures individually so all resources are attempted.
    """
    for entry in dems.values():
        if entry.transformer and not entry.transformer.is_closed:
            try:
                entry.transformer.close()
            except Exception:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize regional DEMs
    app.state.regional_dems = {}
    loaded = init_regional_dems()
    app.state.regional_dems = loaded
    yield
    # Shutdown: Close all owned DEM transformers
    close_regional_dems(getattr(app.state, "regional_dems", {}))
    app.state.regional_dems = {}


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=PROJECT_NAME,
    version=VERSION,
    lifespan=lifespan,
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
