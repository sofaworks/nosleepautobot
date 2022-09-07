from pathlib import Path
from typing import Any

import logging
import sys

from autobot.config import Settings
from moderation.activity import ReportService

from logtail import LogtailHandler

import structlog


def configure_structlog() -> None:
    procs: list[Any] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder()
    ]

    if sys.stderr.isatty():
        procs.append(structlog.dev.ConsoleRenderer())
    else:
        procs.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=procs,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


if __name__ == '__main__':
    configure_structlog()
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO
    )
    log = structlog.get_logger()
    cfg = Settings()

    if cfg.logtail_token:
        root_log = logging.getLogger()
        lth = LogtailHandler(source_token=cfg.logtail_token)
        root_log.addHandler(lth)

    cd = Path(__file__).resolve().parent
    td = cd / "moderation" / "templates"
    svc = ReportService(cfg, td, log)
    svc.run(interval=600)
