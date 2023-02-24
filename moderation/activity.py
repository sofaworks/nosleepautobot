#!/usr/bin/env python3

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar, Sequence

import dataclasses
import datetime
import random
import re
import time

from autobot.config import Settings

from mako.lookup import TemplateLookup
from praw.exceptions import RedditAPIException
from praw.models import Redditor

import praw
import redis
import schedule
import structlog


@dataclass
class ModActivity:
    moderator: str
    begin: datetime.datetime
    end: datetime.datetime
    active_days: int = 0
    approvelink: int = 0
    removelink: int = 0
    approvecomment: int = 0
    removecomment: int = 0


class ReportService:
    exempt_mods: ClassVar[Sequence[str]] = ("nosleepautobot", "automoderator")
    actions: ClassVar[Sequence[str]] = ('approvelink', 'removelink', 'approvecomment', 'removecomment')
    individual_template: ClassVar[str] = "individual_mod_activity_report.md.template"
    per_user_retries: ClassVar[int] = 10

    def __init__(
        self,
        config: Settings,
        template_dir: PurePath,
        logger: structlog.BoundLogger
    ) -> None:
        self.redis = redis.from_url(config.redis_url, decode_responses=True)
        self.reddit = praw.Reddit(
            user_agent=config.user_agent,
            client_id=config.client_id,
            client_secret=config.client_secret,
            username=config.reddit_username,
            password=config.reddit_password
        )

        self.mako = TemplateLookup([template_dir])

        self.subreddit = self.reddit.subreddit(config.subreddit)
        self.log = logger

        if not self.subreddit.user_is_moderator:
            raise AssertionError("User is not moderator of subreddit.")

        self.moderators = list(self.subreddit.moderator())

    def get_ts(self) -> tuple[datetime.datetime, datetime.datetime]:
        """Convenience method that returns UTC dates for beginning
        of the month and current day."""
        today = datetime.datetime.now(tz=datetime.timezone.utc)
        month_start = datetime.datetime(
            today.year,
            today.month,
            1,
            tzinfo=datetime.timezone.utc
        )
        return (month_start, today)

    def _handle_rate_limit(self, ex: RedditAPIException) -> None:
        units = {
            "second": 1,
            "seconds": 1,
            "minute": 60,
            "minutes": 60,
            "hour": 3600,
            "hours": 3600
        }
        m = re.search(
                r"(?P<number>[0-9]+) (?P<unit>\w+)s? before trying.*\.$",
                ex.message,
                re.IGNORECASE
            )
        if not m:
            self.log.error(
                "Unable to parse rate limit message",
                msg=ex.message
            )
            return

        self.log.info("Rate limit found", limit=m)
        delay = int(m["number"]) * units[m["unit"]]
        # sleep with jitter - reddit has multiple rate limits in place
        # for the API calls that surround report generation, so there
        # may be subsequent rate limits after the first one
        time.sleep(delay + random.randint(2, 100))

    def summarize_and_send(self, moderator: Redditor, msg_title: str) -> None:
        template = self.mako.get_template(self.individual_template)
        for _ in range(self.per_user_retries):
            try:
                activity = self.generate_summary(moderator.name)
                message = template.render(**dataclasses.asdict(activity))
                moderator.message(subject=msg_title, message=message)
                break
            except RedditAPIException as e:
                self.log.error("Received exception", ex=e)
                rate_limited = False
                for subex in e.items:
                    if subex.error_type == "RATELIMIT":
                        rate_limited = True
                        self._handle_rate_limit(e)
                if not rate_limited:
                    break

    def gen_all_reports(self) -> None:
        self.log.info("ReportService preparing to generate all reports.")
        for mod in self.moderators:
            if mod.name.lower() in self.exempt_mods:
                continue

            self.summarize_and_send(
                mod,
                f"r/{self.subreddit.display_name} moderation minimum activity reminder"
            )

    def generate_summary(self, moderator: str) -> ModActivity:
        self.log.info(f"Generating mod report for {moderator}.")

        start, now = self.get_ts()
        start_ts = int(start.timestamp())

        action_days = set()
        action_counts: dict[str, int] = defaultdict(int)
        for action in self.actions:
            mod_actions = self.subreddit.mod.log(
                action=action,
                mod=moderator,
                limit=500
            )
            for a in mod_actions:
                if a.created_utc > start_ts:
                    action_counts[action] += 1
                    ds = datetime.datetime.fromtimestamp(
                            a.created_utc,
                            tz=datetime.timezone.utc)
                    action_days.add(ds.toordinal())
        return ModActivity(
                moderator=moderator,
                begin=start,
                end=now,
                active_days=len(action_days),
                **action_counts)

    def process_adhoc_requests(self) -> None:
        mark_queue = []
        reqs = defaultdict(list)
        for msg in self.reddit.inbox.unread(limit=None):
            if (not msg.author
                    or msg.author.name.lower() not in self.moderators):
                self.log.info(
                    "Ignoring message",
                    author=msg.author,
                    subject=msg.subject
                )
                mark_queue.append(msg)

            if msg.subject.strip().lower() != "moderator activity":
                mark_queue.append(msg)
            else:
                reqs[msg.author].append(msg)

        # process all of a moderator's requests as a single unit
        for mod, msgs in reqs.items():
            self.log.info(
                "Processing ad-hoc activity request",
                moderator=mod.name
            )
            self.summarize_and_send(
                mod,
                f"Your requested activity for r/{self.subreddit.display_name}"
            )
            mark_queue.extend(msgs)
        self.reddit.inbox.mark_read(mark_queue)

    def run_weekly_report(self) -> None:
        key = f"reportservice.{self.subreddit.display_name}.weekly.last_run"
        month_start, now = self.get_ts()
        last_run = self.redis.get(key)
        if not last_run or int(last_run) < int(now.timestamp()):
            self.log.info("Running weekly job report", last_run=last_run)
            self.gen_all_reports()
            self.log.info(
                "Finished weekly activity report",
                previous_run=last_run,
                latest_run=int(now.timestamp()))
            self.redis.set(key, int(now.timestamp()))
        else:
            self.log.info("Skipping running weekly report", last_run=last_run)

    def run(self, interval: int = 600) -> None:
        schedule.every(interval).seconds.do(self.process_adhoc_requests)
        schedule.every().friday.at("12:01").do(self.run_weekly_report)

        while True:
            self.log.info("[report service] Running pending report jobs.")
            schedule.run_pending()
            self.log.info("[report service] Sleeping the report service.")
            time.sleep(interval)
