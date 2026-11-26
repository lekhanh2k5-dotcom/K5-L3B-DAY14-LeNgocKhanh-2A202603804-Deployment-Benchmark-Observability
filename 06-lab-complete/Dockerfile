# ============================================================
# Production Dockerfile — Part 6 (tiêu chí 1)
#   • Multi-stage: builder cài dependencies vào venv, runtime chỉ copy venv + code
#   • Base slim, user non-root, có HEALTHCHECK
#   • uvicorn là PID 1 (exec) → nhận SIGTERM trực tiếp khi `docker stop`
#   • Lắng nghe theo biến PORT do Railway / Render cấp (mặc định 8000)
# Build từ thư mục 06-lab-complete/:  docker build -t day14-agent .
# ============================================================

# ── Stage 1: builder ────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
# requirements trước, code sau: đổi code không làm mất cache layer cài thư viện
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt

# ── Stage 2: runtime ────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    WEB_CONCURRENCY=2

RUN groupadd --system app && useradd --system --gid app --uid 10001 --no-create-home app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/
COPY --chown=app:app utils/ ./utils/

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'), timeout=3)" || exit 1

# sh -c để thay ${PORT}; `exec` để uvicorn thay chỗ shell và làm PID 1
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-2} --timeout-graceful-shutdown 8"]
