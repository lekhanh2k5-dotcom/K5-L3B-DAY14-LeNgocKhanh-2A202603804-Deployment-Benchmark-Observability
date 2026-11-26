"""
Production AI Agent — Part 6 Final Project

Chạy:  uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
Chấm:  python check_production_ready.py
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.config import settings
from app.logging_config import setup_logging

# Cấu hình log TRƯỚC khi import các module có thể ghi log (bài học từ Part 1)
setup_logging(settings.log_level)

from app.auth import verify_api_key  # noqa: E402
from app.cost_guard import check_budget, estimate_tokens, record_cost  # noqa: E402
from app.rate_limiter import check_rate_limit  # noqa: E402
from app.redis_client import r, redis_healthy  # noqa: E402
from utils.mock_llm import ask as llm_ask  # noqa: E402

logger = logging.getLogger("agent")

START_TIME = time.time()
_shutting_down = False


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


# ──────────────────────────────────────────────────────────
# Lifecycle — graceful shutdown (tiêu chí 11)
# Uvicorn bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong,
# rồi mới chạy phần sau `yield`. Không tự đăng ký signal handler để khỏi đè handler của uvicorn.
# ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _shutting_down
    log_event("startup", environment=settings.environment, version=settings.app_version,
              rate_limit_per_minute=settings.rate_limit_per_minute,
              daily_budget_usd=settings.daily_budget_usd,
              monthly_budget_usd=settings.monthly_budget_usd,
              api_key_configured=bool(settings.agent_api_key))
    if not settings.agent_api_key:
        log_event("config_warning", logging.WARNING,
                  detail="AGENT_API_KEY is empty: every /ask request will get 401")
    yield
    _shutting_down = True
    log_event("shutdown", detail="in-flight requests finished, closing Redis connections",
              uptime_seconds=round(time.time() - START_TIME, 1))
    try:
        r.close()
    except RedisError:
        pass


app = FastAPI(title="Production AI Agent", version=settings.app_version, lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs",
              redoc_url=None)


# ──────────────────────────────────────────────────────────
# Middleware: 1 dòng log JSON cho mỗi request
# ──────────────────────────────────────────────────────────
@app.middleware("http")
async def access_log(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log_event("request_failed", logging.ERROR, request_id=request_id, method=request.method,
                  path=request.url.path, ms=round((time.perf_counter() - started) * 1000, 1))
        raise
    response.headers["X-Request-ID"] = request_id
    log_event("request", request_id=request_id, method=request.method, path=request.url.path,
              status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response


# ──────────────────────────────────────────────────────────
# Xử lý lỗi: mã lỗi rõ ràng, không lộ stack trace ra client
# ──────────────────────────────────────────────────────────
@app.exception_handler(RedisError)
async def redis_error_handler(request: Request, exc: RedisError):
    log_event("dependency_error", logging.ERROR, dependency="redis", error=type(exc).__name__,
              path=request.url.path)
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable (state store)"},
                        headers={"Retry-After": "5"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.error("unhandled_error", exc_info=exc, extra={"fields": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ──────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = Field(default=None, max_length=128)


# ──────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"app": "Production AI Agent", "version": settings.app_version,
            "environment": settings.environment,
            "endpoints": ["GET /health", "GET /ready", "POST /ask (X-API-Key)"]}


@app.get("/health")
def health():
    """Liveness (tiêu chí 4): process còn sống là 200 — không phụ thuộc Redis."""
    return {"status": "ok", "uptime_seconds": round(time.time() - START_TIME, 1),
            "version": settings.app_version, "environment": settings.environment,
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/ready")
def ready():
    """Readiness (tiêu chí 5): 503 khi đang tắt hoặc Redis không kết nối được."""
    if _shutting_down:
        return JSONResponse(status_code=503, content={"ready": False, "reason": "shutting down"})
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"ready": False, "reason": "redis unreachable"})
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, response: Response, api_key: str = Depends(verify_api_key)):
    # 1) Rate limit theo API key (429)   2) Budget (402)   3) Gọi LLM   4) Ghi chi phí
    rate = check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)

    input_tokens, output_tokens = estimate_tokens(body.question), estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)

    response.headers["X-RateLimit-Limit"] = str(rate["limit"])
    response.headers["X-RateLimit-Remaining"] = str(rate["remaining"])
    log_event("ask", question_length=len(body.question), answer_length=len(answer),
              input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cost_usd": round(cost, 8), "requests_remaining": rate["remaining"]}}
