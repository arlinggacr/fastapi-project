import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.router import api_router, ws_router
from src.core.config import get_settings
from src.core.realtime import Broker
from src.core.redis import create_gateway
from src.database.session import engine
from src.middlewares.security import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from src.modules.auctions.services.scheduler import AuctionScheduler
from src.utils.responses import (
    ClientError,
    ErrorEnvelope,
    SuccessEnvelope,
    error,
    from_http_exception,
    success,
)

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

# In REST mode every Redis operation is one HTTPS POST, so httpx would log a
# line per call and drown the application logs. Keep its warnings and errors.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    gateway = create_gateway(settings)
    try:
        await gateway.ping()
    except Exception:
        logger.exception("redis ping failed - realtime features will be unavailable")

    broker = Broker(gateway, poll_interval=settings.rest_poll_interval)
    scheduler = AuctionScheduler(gateway, broker)

    app.state.gateway = gateway
    app.state.broker = broker
    app.state.scheduler = scheduler
    scheduler.start()

    logger.info("app ready (redis backend: %s)", settings.redis_mode)
    try:
        yield
    finally:
        await scheduler.stop()
        await gateway.close()
        await engine.dispose()
        logger.info("app shut down")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Realtime auction API. Users list their own items; anyone except the "
        "seller can bid. Live updates over WebSockets, backed by Redis.\n\n"
        "Every response uses one of two envelopes:\n"
        "- success: `{status: true, data, message, pagination}`\n"
        "- error: `{status: false, message, error}`"
    ),
    lifespan=lifespan,
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
    responses={500: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope}},
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router)
app.include_router(ws_router)


@app.exception_handler(ClientError)
async def client_error_handler(request: Request, exc: ClientError) -> JSONResponse:
    """Domain errors carry their own status code and safe details."""
    return error(exc)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Covers FastAPI's HTTPException (and therefore ApiError) plus routing 404/405."""
    return from_http_exception(exc)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Request validation failures use the C# validation branch: 400 + message list."""
    messages = [
        f"{'.'.join(str(part) for part in err['loc'][1:]) or 'body'}: {err['msg']}"
        for err in exc.errors()
    ]
    return error(messages)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak stack traces or driver messages to clients."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return error(exc)


@app.get("/", tags=["meta"], response_model=SuccessEnvelope[dict[str, Any]])
async def root() -> dict[str, Any]:
    return success(
        {
            "name": settings.app_name,
            "docs": "/docs" if settings.enable_docs else None,
            "realtime": settings.redis_mode,
            "websockets": ["/ws/auctions/{id}?token=", "/ws/me?token="],
        },
        "Service info",
    )


@app.get("/health", tags=["meta"], response_model=SuccessEnvelope[dict[str, Any]])
async def health() -> dict[str, Any]:
    gateway = app.state.gateway
    redis_ok = False
    try:
        redis_ok = await gateway.ping()
    except Exception:
        pass
    return success(
        {"status": "ok" if redis_ok else "degraded", "redis": redis_ok},
        "Service is healthy" if redis_ok else "Service is degraded",
    )
