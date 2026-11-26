"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày và theo tháng (UTC)
  • Tổng chi phí chạm DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402
  • Budget = 0 nghĩa là tắt giới hạn đó
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _keys() -> tuple:
    now = datetime.now(timezone.utc)
    return f"cost:daily:{now:%Y-%m-%d}", f"cost:monthly:{now:%Y-%m}"


def estimate_tokens(text: str) -> int:
    """Ước lượng thô ~4 ký tự / token (mock LLM không trả usage thật)."""
    return max(1, (len(text) + 3) // 4)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_key, monthly_key = _keys()
    daily_raw, monthly_raw = r.mget(daily_key, monthly_key)
    spent = {"daily": float(daily_raw or 0), "monthly": float(monthly_raw or 0)}
    limits = {"daily": settings.daily_budget_usd, "monthly": settings.monthly_budget_usd}
    for period in ("daily", "monthly"):
        if limits[period] > 0 and spent[period] >= limits[period]:
            raise HTTPException(
                status_code=402,
                detail={"error": f"{period.capitalize()} budget exceeded",
                        "spent_usd": round(spent[period], 6), "budget_usd": limits[period]},
            )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    daily_key, monthly_key = _keys()
    pipe = r.pipeline(transaction=True)
    pipe.incrbyfloat(daily_key, cost)          # INCRBYFLOAT là thao tác nguyên tử của Redis
    pipe.expire(daily_key, 2 * 24 * 3600)
    pipe.incrbyfloat(monthly_key, cost)
    pipe.expire(monthly_key, 32 * 24 * 3600)
    pipe.execute()
    return cost
