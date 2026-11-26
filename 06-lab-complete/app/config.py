"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường (tiêu chí 9).

Không có secret nào nằm trong code. Giá trị mặc định chỉ dùng cho máy local;
trên Railway / Render các biến được đặt trong dashboard của nền tảng.
"""
import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    # Server
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    app_version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "1.0.0"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # Security — không có giá trị mặc định: thiếu key thì /ask từ chối mọi request
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    # State dùng chung (rate limit, cost guard)
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Giới hạn
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _env_float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _env_float("MONTHLY_BUDGET_USD", 10.0))

    def validate(self) -> "Settings":
        """Fail fast: cấu hình sai thì không khởi động, thay vì chạy sai."""
        if self.environment == "production" and not self.agent_api_key:
            raise RuntimeError("AGENT_API_KEY must be set when ENVIRONMENT=production")
        if self.rate_limit_per_minute < 1:
            raise ValueError("RATE_LIMIT_PER_MINUTE must be >= 1")
        if self.daily_budget_usd < 0 or self.monthly_budget_usd < 0:
            raise ValueError("budgets must be >= 0 (0 = disabled)")
        return self


settings = Settings().validate()
