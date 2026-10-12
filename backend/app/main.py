"""FastAPI application entry point."""
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.chat import router as chat_router
from app.api.routes.artifacts import router as artifact_router
from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.core.rag_diagnostics import request_id_context

settings = get_settings()
configure_logging()
logger = logging.getLogger("lenny.api")
app = FastAPI(title=settings.app_name)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "X-CSRF-Token"], expose_headers=["X-CSRF-Token", "X-Request-ID"])
app.include_router(health_router)
app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(chat_router, prefix=settings.api_v1_prefix)
app.include_router(artifact_router, prefix=settings.api_v1_prefix)


@app.middleware("http")
async def request_log(request: Request, call_next):
    """Set request context within the downstream task and log the final response."""
    request_id = str(uuid4())
    started = time.perf_counter()
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_context.reset(token)
    route = request.scope.get("route")
    logger.info("request_complete", extra={
        "event": "request_complete", "request_id": request_id, "method": request.method,
        "route": getattr(route, "path", "unmatched"), "status_code": response.status_code,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    })
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(SQLAlchemyError)
async def database_unavailable(_request: Request, _exc: SQLAlchemyError):
    return JSONResponse(status_code=503, content={"detail": "Chat storage is unavailable. Check the database connection and schema permissions."})


@app.exception_handler(RuntimeError)
async def service_unavailable(_request: Request, _exc: RuntimeError):
    return JSONResponse(status_code=503, content={"detail": "The answer service is unavailable. Check the configured RAG and LLM providers."})
