from pathlib import Path

import argparse
import logging
import sys
import traceback

from autobot.bot import AutoBot
from autobot.config import Settings
from autobot.models import SubmissionHandler
from autobot.util.messages.templater import MessageBuilder

import redis
import rollbar
from rollbar.logger import RollbarHandler


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
    logging.critical("Got an uncaught exception")
    logging.critical("".join(traceback.format_tb(tb)))
    logging.critical(f"{ex_type}: {value}")


def init_rollbar(token: str, environment: str) -> None:
    rollbar.init(token, environment)
    rollbar_handler = RollbarHandler()
    rollbar_handler.setLevel(logging.ERROR)
    logging.getLogger("autobot").addHandler(rollbar_handler)


def transform_and_roll_out() -> None:
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    sys.excepthook = uncaught_ex_handler

    parser = create_argparser()
    args = parser.parse_args()

    settings = Settings()

    if settings.rollbar_token:
        init_rollbar(settings.rollbar_token, settings.rollbar_env)

    logging.info(f"Using redis({settings.redis_url}) for redis")
    rd = redis.Redis.from_url(settings.redis_url)
    hd = SubmissionHandler(rd)
    cd = Path(__file__).resolve().parent
    td = cd / "autobot" / "util" / "messages" / "templates"
    print(td)
    mb = MessageBuilder(td)
    AutoBot(settings, hd, mb).run(args.forever, args.interval)


if __name__ == "__main__":
    transform_and_roll_out()
