"""
Rate limiting (tiêu chí 7) — sliding window log trên Redis sorted set.

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây
  • Vượt giới hạn → HTTP 429 kèm Retry-After
  • State nằm trong Redis: mọi worker / instance dùng chung, restart agent vẫn còn
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket(key: str) -> str:
    # Không lưu API key gốc vào Redis, chỉ lưu hash
    return "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def check_rate_limit(key: str) -> dict:
    limit = settings.rate_limit_per_minute
    now = time.time()
    bucket = _bucket(key)
    member = f"{now:.6f}-{uuid.uuid4().hex[:8]}"

    # Một transaction: bỏ mốc cũ → ghi request này → đếm. Ghi trước rồi mới đếm nên
    # hai worker nhận request cùng lúc không thể cùng thấy "còn chỗ".
    pipe = r.pipeline(transaction=True)
    pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
    pipe.zadd(bucket, {member: now})
    pipe.zcard(bucket)
    pipe.expire(bucket, WINDOW_SECONDS + 1)
    _, _, count, _ = pipe.execute()

    if count > limit:
        r.zrem(bucket, member)  # request bị từ chối không chiếm chỗ trong cửa sổ
        oldest = r.zrange(bucket, 0, 0, withscores=True)
        retry_after = int(oldest[0][1] + WINDOW_SECONDS - now) + 1 if oldest else WINDOW_SECONDS
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": limit,
                    "window_seconds": WINDOW_SECONDS, "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": str(limit),
                     "X-RateLimit-Remaining": "0"},
        )
    return {"limit": limit, "remaining": limit - count}
