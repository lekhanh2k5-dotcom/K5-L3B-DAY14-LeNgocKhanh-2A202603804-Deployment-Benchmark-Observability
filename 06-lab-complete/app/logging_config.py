"""
Structured logging (tiêu chí 10): mỗi dòng log của app là đúng một JSON object.

Dùng:
    logger.info("request", extra={"fields": {"path": "/ask", "status": 200}})
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        # default=str: giá trị lạ (datetime, Exception...) vẫn ra JSON hợp lệ
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Gắn JSON formatter cho root logger. Log của uvicorn có handler riêng nên không bị ảnh hưởng."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
