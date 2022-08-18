from collections.abc import Iterator, Mapping
import urllib.parse

import logging

from autobot.config import Settings

import praw

PrawSubmissionIter = Iterator[praw.models.Submission]


class MissingFlairException(Exception):
    """Custom exception class when a flair doesn't exist."""
    ...


class SubredditTool:
    def __init__(self, cfg: Settings) -> None:
        self.logger = logging.getLogger("reddit-tool")
        self.read_only = cfg.development_mode
        self.reddit = praw.Reddit(
            user_agent=cfg.user_agent,
            client_id=cfg.client_id,
            client_secret=cfg.client_secret,
            username=cfg.reddit_username,
            password=cfg.reddit_password
        )
        self.subreddit = self.reddit.subreddit(cfg.subreddit)
        if not self.read_only and not self.subreddit.user_is_moderator:
            raise AssertionError(
                    f"User {cfg.reddit_username} is not moderator of "
                    f"subreddit {self.subreddit.display_name}."
            )

    def _get_posts(
        self,
        query: str,
        time_filter: str,
        *,
        syntax: str = "lucene",
        sort: str = "new"
    ) -> PrawSubmissionIter:
        r = self.subreddit.search(
            query, time_filter=time_filter, syntax=syntax, sort=sort
        )
        return r

    def get_recent_posts(self) -> PrawSubmissionIter:
        """Get most recent submissions from the subreddit - right now it
        fetches the last hour's worth of results."""
        self.logger.info("Retrieving submissions from the last hour")
        return self._get_posts(
            f"subreddit:{self.subreddit.display_name}",
            time_filter="hour",
        )

    def get_redditor_posts(
        self,
        redditor: praw.models.Redditor
    ) -> PrawSubmissionIter:
        """Retrieve the data from the API of all the posts made by this author
        in the last 24 hours. This has to be done via cloudsearch because
        Reddit apparently doesn't enable semantic hyphening in their lucene
        indexes, so user names with hyphens in them will return improper
        results."""
        return self._get_posts(
            f'author:"{redditor.name}"',
            time_filter="day",
            syntax="cloudsearch"
        )

    def subreddit_name(self) -> str:
        return self.subreddit.display_name

    def send_series_pm(
        self,
        post: praw.models.Submission,
        msg: str
    ) -> None:
        if not self.read_only:
            try:
                post.author.message(
                    "Reminder about your series post on r/nosleep",
                    msg,
                    None
                )
            except Exception as e:
                self.logger.info(
                    f"Problem sending series message to {post.author.name}: "
                    f"{repr(e)}"
                )
        else:
            self.logger.info(
                "Running in DEVELOPMENT MODE - not PMing series msg"
            )

    def post_series_reminder(
        self,
        post: praw.models.Submission,
        comment: str
    ) -> None:
        self.logger.info(f"Posting series reminder for {post.id}")
        self.add_comment(
            post,
            comment,
            distinguish=True,
            sticky=True,
            lock=True
        )

    def delete_post(self, post: praw.models.Submission) -> None:
        if not self.read_only:
            post.mod.remove()
        else:
            self.logger.info("Running in DEVELOPMENT MODE - not deleting post")

    def add_comment(
        self,
        post: praw.models.Submission,
        msg: str,
        *,
        sticky: bool = False,
        distinguish: bool = False,
        lock: bool = False
    ) -> None:
        """Make a comment on the provided post."""
        if not self.read_only:
            rsp = post.reply(msg)
            dis = "yes" if distinguish else "no"
            rsp.mod.distinguish(how=dis, sticky=sticky)
            if lock:
                rsp.mod.lock()
        else:
            self.logger.info(
                f"Running in DEVELOPMENT MODE - not adding comment: '{msg}'"
            )

    def set_series_flair(
        self,
        post: praw.models.Submission,
        *,
        name: str = "flair-series"
    ) -> None:
        """Set the series flair for a post."""
        if not self.read_only:
            for f in post.flair.choices():
                if f["flair_css_class"].lower() == name.lower():
                    try:
                        post.flair.select(f["flair_template_id"])
                        return
                    except KeyError:
                        # This shouldn't happen
                        raise
            raise MissingFlairException(
                f"Flair class {name} not found for "
                f"subreddit /r/{self.subreddit_name}"
            )
        else:
            self.logger.info("Running in DEVELOPMENT MODE - not flairing post")

    def gen_compose_url(self, query: Mapping[str, str]) -> str:
        qs = urllib.parse.urlencode(query)
        parts = ("https", "www.reddit.com", "message/compose", qs, None)
        return urllib.parse.urlunsplit(parts)

    def create_modmail_link(
        self,
        subject: str | None = None,
        message: str | None = None
    ) -> str:
        q = {
            "to": f"/r/{self.subreddit_name()}",
        }

        if subject:
            q["subject"] = subject

        if message:
            q["message"] = message
        return self.gen_compose_url(q)


