"""structlog configuration: JSON to a rotating file, human-readable to the console.

Context (league_id, season, run_id, source, domain) is bound via contextvars so
every log line carries it without threading it through call signatures.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import uuid
from pathlib import Path

import structlog

from fantrax_analytics.config import LogLevel

_CONFIGURED = False


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def configure_logging(log_dir: Path, level: LogLevel = "INFO", *, json_console: bool = False) -> None:
    """Idempotent logging setup. Safe to call more than once."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    log_dir.mkdir(parents=True, exist_ok=True)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "fantrax.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    )

    console_renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_console
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, console_renderer],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.setLevel(level)
    # Third-party noise stays in the file but off the console at INFO.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    _CONFIGURED = True


def bind_run_context(**kwargs: object) -> None:
    structlog.contextvars.bind_contextvars(**kwargs)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
