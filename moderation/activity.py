#!/usr/bin/env python3

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar, Sequence

import dataclasses
import datetime
import time

from autobot.config import Settings

from mako.lookup import TemplateLookup

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

    def gen_all_reports(self) -> None:
        self.log.info("ReportService preparing to generate all reports.")
        template = self.mako.get_template(self.individual_template)
        for mod in self.moderators:
            if mod.name.lower() in self.exempt_mods:
                continue

            activity = self.generate_summary(mod.name)
            mod.message(
                f"r/{self.subreddit.display_name} moderation minimum activity reminder",
                template.render(**dataclasses.asdict(activity))
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
                    action_days.add(ds.toordinal)
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
            self.log.info("Processing ad-hoc activity request", moderator=mod)
            report = self.generate_summary(mod.name)
            mod.message(subject="Your requested activity", message=report)
            mark_queue.extend(msgs)
        self.reddit.inbox.mark_read(mark_queue)

    def run_weekly_report(self) -> None:
        key = "reportservice.weekly.last_run"
        start, now = self.get_ts()
        last_run = self.redis.get(key)
        if not last_run or int(last_run) < int(start.timestamp()):
            self.log.info("Running weekly job report", last_run=last_run)
            self.gen_all_reports()
            self.log.info(
                "Finished weekly activity report",
                previous_run=last_run,
                latest_run=now.timestamp())
            self.redis.set(key, now.timestamp())
        else:
            self.log.info("Skipping running weekly report", last_run=last_run)

    def run(self, interval: int = 600) -> None:
        schedule.every(interval).seconds.do(self.process_adhoc_requests)
        schedule.every().friday.at("12:01").do(self.run_weekly_report)

        while True:
            self.log.info("Running pending report jobs.")
            schedule.run_pending()
            time.sleep(interval)
