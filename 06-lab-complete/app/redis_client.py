"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Đọc REDIS_URL từ config
  • redis.from_url() không mở kết nối lúc import → app vẫn khởi động được khi Redis chưa sẵn sàng
  • Timeout ngắn để /ready trả 503 nhanh thay vì treo khi Redis chết
"""
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Optional

import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=2,
    health_check_interval=30,
)


def _ping() -> bool:
    try:
        return bool(r.ping())
    except redis.exceptions.RedisError:
        return False


# socket_connect_timeout không tính thời gian tra DNS: khi host Redis biến mất (container bị
# dừng) một lần ping có thể treo ~8 giây. Chạy ping ở thread riêng và chỉ chờ tối đa
# READY_TIMEOUT; dùng lại lượt ping đang chạy dở để không sinh thêm thread.
READY_TIMEOUT = 1.5
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="redis-ready")
_pending: Optional[Future] = None


def redis_healthy() -> bool:
    """Dùng cho GET /ready: Redis không kết nối được (hoặc quá READY_TIMEOUT) → False."""
    global _pending
    if _pending is None or _pending.done():
        _pending = _executor.submit(_ping)
    try:
        return _pending.result(timeout=READY_TIMEOUT)
    except FutureTimeout:
        return False
