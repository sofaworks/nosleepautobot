from collections.abc import Iterator, Mapping
import urllib.parse

from autobot.config import Settings

import praw
import structlog

PrawSubmissionIter = Iterator[praw.models.Submission]


class MissingFlairException(Exception):
    """Custom exception class when a flair doesn't exist."""
    ...


class SubredditTool:
    def __init__(self, cfg: Settings) -> None:
        self.logger = structlog.get_logger()
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

    def is_post_deleted(self, post_id: str) -> bool:
        submission = self.reddit.submission(post_id)
        if (
            submission.removed
            or not submission.author
            or not submission.is_robot_indexable
        ):
            return True
        return False

    def retrieve_new_posts(
        self,
        *,
        before: praw.models.Submission | None = None,
    ) -> PrawSubmissionIter:
        """This does essentially what search_recent_posts does, but
        gets new posts by using the 'new' endpoint, which returns
        recent posts faster than searching for them."""
        self.logger.info(f"Fetching for before: {before}")

        # safety check in case the 'before' got deleted between
        # the last time we used it
        if before:
            if self.is_post_deleted(before.id):
                self.logger.info(
                    "Post was removed, not using 'before' parameter",
                    subreddit=before.subreddit.display_name,
                    id=before.id)
                before = None
        params = {"before": before.name} if before else {}
        return self.subreddit.new(params=params)

    def search_recent_posts(self) -> PrawSubmissionIter:
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
            syntax="lucene"
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
                self.logger.info(
                    "Sending Series PM",
                    post_id=post.id,
                    author=post.author
                )
                post.author.message(
                    "Reminder about your series post on r/nosleep",
                    msg,
                    None
                )
            except Exception:
                self.logger.exception(
                    "Problem sending series message",
                    author=post.author.name
                )
        else:
            self.logger.info(
                "Running in DEVELOPMENT MODE - not PMing series msg",
                post_id=post.id,
                author=post.author
            )

    def post_series_reminder(
        self,
        post: praw.models.Submission,
        comment: str
    ) -> None:
        self.logger.info("Adding series subscribeme comment ", post_id=post.id)
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
            self.logger.info(
                "Running in DEVELOPMENT MODE - not deleting post",
                post_id=post.id,
                author=post.author.name
            )

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
            self.logger.info(
                "Creating comment on post",
                post_id=post.id,
                author=post.author.name,
                sticky=sticky,
                distinguish=distinguish,
                lock=lock
            )
            rsp = post.reply(msg)
            dis = "yes" if distinguish else "no"
            rsp.mod.distinguish(how=dis, sticky=sticky)
            if lock:
                rsp.mod.lock()
        else:
            self.logger.info(
                "Running in DEVELOPMENT MODE - not adding comment",
                post_id=post.id,
                author=post.author.name
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
                        self.logger.exception("Unexpected exception")
                        raise
            raise MissingFlairException(
                f"Flair class {name} not found for "
                f"subreddit /r/{self.subreddit_name}"
            )
        else:
            self.logger.info(
                "Running in DEVELOPMENT MODE - not flairing post",
                post_id=post.id,
                author=post.author
            )

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


