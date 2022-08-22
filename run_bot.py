#!/usr/bin/env python3
from pathlib import Path

import argparse
import logging
import sys
import traceback

from autobot.autobot import AutoBot
from autobot.config import Settings
from autobot.models import SubmissionHandler
from autobot.util.messages.templater import MessageBuilder

import redis
import rollbar
import structlog


def configure_structlog() -> None:
    procs = [
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


def create_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_bot.py")
    parser.add_argument(
        "--forever",
        required=False,
        action="store_true",
        help="If specified, runs bot forever."
    )
    parser.add_argument(
        "-i",
        "--interval",
        required=False,
        type=int,
        default=300,
        help="Seconds to wait between run cycles, if 'forever' is specified."
    )
    return parser


def uncaught_ex_handler(ex_type, value, tb) -> None:
    log = structlog.get_logger()
    log.critical("Got an uncaught exception")
    log.critical("".join(traceback.format_tb(tb)))
    log.critical(f"{ex_type}: {value}")
    rollbar.report_exc_info()


def init_rollbar(token: str, environment: str) -> None:
    rollbar.init(token, environment)


def transform_and_roll_out() -> None:
    configure_structlog()
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )
    log = structlog.get_logger()
    sys.excepthook = uncaught_ex_handler

    parser = create_argparser()
    args = parser.parse_args()

    settings = Settings()

    if settings.rollbar_token:
        init_rollbar(settings.rollbar_token, settings.rollbar_env)

    rd = redis.Redis.from_url(settings.redis_url)
    hd = SubmissionHandler(rd)
    cd = Path(__file__).resolve().parent
    td = cd / "autobot" / "util" / "messages" / "templates"
    log_params = {
        "development_mode": settings.development_mode,
        "template_directory": str(td),
        "moderating_subreddit": settings.subreddit,
        "enforcing_timelimit": settings.enforce_timelimit,
        "timelimit": settings.post_timelimit,
        "reddit_user": settings.reddit_username
    }
    log.info("Bot starting", **log_params)
    mb = MessageBuilder(td)
    AutoBot(settings, hd, mb).run(args.forever, args.interval)


if __name__ == "__main__":
    transform_and_roll_out()
