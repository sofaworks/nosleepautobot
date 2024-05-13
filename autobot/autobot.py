from collections.abc import Iterable
from dataclasses import dataclass
from operator import attrgetter
from typing import Any
import json
import re
import time

from autobot.config import Settings
from autobot.models import Activity, DataStore, Submission
from autobot.util.messages.templater import MessageBuilder
from autobot.util.reddit_util import SubredditTool

import praw
import redis
import structlog


logger = structlog.get_logger()


def englishify_time(seconds: float) -> str:
    """Converts seconds into a string describing how long it is in
    readable time."""
    i = int(seconds)
    hours, minutes = divmod(i, 3600)
    minutes, seconds = divmod(minutes, 60)

    return f"{hours} hours, {minutes} minutes, {seconds} seconds"


@dataclass
class PostMetadata:
    """Data class for various properties we derive
    from a post."""
    has_long_paragraphs: bool = False
    has_codeblocks: bool = False
    has_nsfw_title: bool = False
    is_series: bool = False
    is_final: bool = False
    invalid_tags: Iterable[str] | None = None

    def is_invalid(self) -> bool:
        bad_things = (
            self.has_long_paragraphs,
            self.has_codeblocks,
            self.has_nsfw_title,
            self.invalid_tags
        )
        return any(bad_things)

    def is_serial(self) -> bool:
        return self.is_series or self.is_final

    def bad_tags(self) -> str:
        if not self.invalid_tags:
            return ""
        return ", ".join(self.invalid_tags)


class PostAnalyzer:
    def __init__(self, series_flair: str):
        self.series_flair = series_flair.lower()

    def categorize_tags(self, title: str) -> tuple[bool, bool, Iterable[str]]:
        """Parses tags out of the post title
        Valid submission tags are things between [], {}, (), and ||

        Valid tag values are:

        * a single number (shorthand for part #)
        * Pt/Pt./Part + number (integral or textual)
        * Vol/Vol./Volume  + number (integral or textual)
        * Update
        * Final
        * Finale
        """
        invalid_tags = []
        is_series = False
        is_final = False

        # This was previously an extremely long regex that matched for a bunch
        # of textual numbers like 'one', 'two', 'fifteen', etc. But it didn't
        # really seem necessary so this is just a basic match of 3+ chars
        # as the shortest number you can make with letters is length 3.
        num_text_pattern = (
            r"(?:[1-9][0-9]*|one|two|three|five|ten|eleven|twelve|fifteen"
            r"|(?:(?:four|six|seven|eight|nine)(?:teen)?))"
        )

        final_pattern = r"finale?"

        series_patterns = {
            "number_only": rf"{num_text_pattern}",
            "part": rf"(?:part|pt\.?)\s?{num_text_pattern}",
            "volume": rf"vol(?:\.|ume)?\s{num_text_pattern}",
            "update": rf"update(?:[ ]#?{num_text_pattern}?)?",
        }

        captures = re.findall(
            r"(\[[^]]*\]|\(.*?\)|\{.*?\}|\|.*?\|)",
            title
        )

        for c in captures:
            if re.search(final_pattern, c, re.IGNORECASE):
                is_series = True
                is_final = True
            elif any(re.fullmatch(p, c[1:-1].strip(), re.IGNORECASE)
                     for p in series_patterns.values()):
                is_series = True
            else:
                invalid_tags.append(c)
        return is_series, is_final, invalid_tags

    def contains_long_paragraphs(
        self,
        paragraphs: Iterable[str],
        max_word_count: int = 350
    ) -> bool:
        for p in paragraphs:
            if max_word_count < len(re.findall(r"\w+", p)):
                return True
        return False

    def contains_nsfw_title(self, title: str) -> bool:
        remap_chars = "{}[]()|.!?$*@#"
        exclude_map = {
            ord(c): ord(t) for c, t in zip(remap_chars, " " * len(remap_chars))
        }
        parts = title.lower().translate(exclude_map).split()
        return any("nsfw" == w.strip() for w in parts)

    def contains_codeblocks(self, paragraphs: Iterable[str]) -> bool:
        """Determines if any paragraph (which is just a str) contains
        codeblocks, which are at least 4 spaces or a tab character starting
        a paragraph. Lines that only have whitespace characters do not
        count as having 'codeblocks'."""
        for p in paragraphs:
            # means this is just a blank line
            if not p.strip():
                continue
            if p.startswith(" "*4) or p.lstrip(" ").startswith("\t"):
                return True
        return False

    def analyze(self, post: praw.models.Submission) -> PostMetadata:
        paragraphs = re.split(r"(?:\n\s*\n|[ \t]{2,}\n|\t\n)", post.selftext)
        series, final, bad_tags = self.categorize_tags(post.title)
        if not series:
            try:
                series = post.link_flair_css_class.lower() == self.series_flair
            except AttributeError:
                pass
        meta = PostMetadata(
            has_long_paragraphs=self.contains_long_paragraphs(paragraphs),
            has_codeblocks=self.contains_codeblocks(paragraphs),
            has_nsfw_title=self.contains_nsfw_title(post.title),
            is_series=series,
            is_final=final,
            invalid_tags=bad_tags
        )
        return meta


class AutoBot:
    def __init__(
        self,
        cfg: Settings,
        db: redis.Redis,
        msg_builder: MessageBuilder
    ):
        self.cfg = cfg
        self.post_db = DataStore(db, Submission)
        self.activity_db = DataStore(db, Activity)
        self.msg_bld = msg_builder
        self.reddit = SubredditTool(cfg)
        self.analyzer = PostAnalyzer(cfg.series_flair_name)
        self.cache_ttl = cfg.post_timelimit * 2
        self.series_flair_name = cfg.series_flair_name
        self.latest_post = None

    def reject_by_timelimit(self, post: praw.models.Submission) -> bool:
        """Determine if a submission should be removed based on a time-limit
        for submissions for a subreddit.

        If a post is rejected, add a comment to the post."""
        if not self.cfg.enforce_timelimit:
            return False

        now = int(time.time())
        if (now - post.created_utc) > self.cfg.post_timelimit:
            return False

        rejected = False
        # look in the cache to see if this user has recent activity
        act = self.activity_db.get(post.author.name)
        if (
            act
            and act.last_post_id != post.id
            and not self.reddit.is_post_deleted(act.last_post_id)
        ):
            td = post.created_utc - int(act.last_post_time.timestamp())
            allowed_when = self.cfg.post_timelimit - td
            if allowed_when > 0:
                rejected = True
                human_fmt = englishify_time(allowed_when)
                log_params = {
                    "reason": "time limit",
                    "permanent": True,
                    "post_id": post.id,
                    "old_post_id": act.last_post_id,
                    "author": post.author.name,
                    "post_timestamp": post.created_utc,
                    "old_post_timestamp": act.last_post_time.timestamp(),
                    "can_post_in": allowed_when,
                }
                logger.info("Rejecting post and notifying author", **log_params)
                msg = self.msg_bld.create_post_a_day_msg(
                    human_fmt,
                    self.reddit.create_modmail_link()
                )
                self.reddit.add_comment(post, msg, distinguish=True)
                self.reddit.delete_post(post)

        return rejected

    def gen_series_reminder(self, post: praw.models.Submission) -> str:
        q = {
            "to": "UpdateMeBot",
            "subject": "Subscribe",
            "message": ("SubscribeMe! "
                        f"/r/{self.reddit.subreddit_name()} /u/{post.author}")
        }
        sub_url = self.reddit.gen_compose_url(q)
        return self.msg_bld.create_series_comment(sub_url)

    def prepare_delete_message(
        self,
        post: praw.models.Submission,
        post_meta: PostMetadata
    ) -> str:

        modmail_link = self.reddit.create_modmail_link()

        if post_meta.invalid_tags:
            reapproval_msg = self.msg_build.create_title_approval_msg(post.shortlink)
        else:
            reapproval_msg = self.msg_bld.create_approval_msg(post.shortlink)

        reapproval_link = self.reddit.create_modmail_link(
                "Please reapprove submission",
                reapproval_msg
        )

        return self.msg_bld.create_deleted_post_msg(
            post.shortlink,
            modmail_link=modmail_link,
            reapproval_modmail=reapproval_link,
            has_nsfw_title=post_meta.has_nsfw_title,
            has_codeblocks=post_meta.has_codeblocks,
            long_paragraphs=post_meta.has_long_paragraphs,
            invalid_tags=post_meta.bad_tags()
        )

    def post_series_reminder(self, submission: praw.models.Submission) -> None:
        """Convenience method that posts the 'this is a series' comment
        on submissions."""
        series_comment = self.gen_series_reminder(submission)
        self.reddit.post_series_reminder(submission, series_comment)

    def send_series_pm(self, submission: praw.models.Submission) -> None:
        """Convenience method that DMs an author the series reminder text."""
        msg = self.msg_bld.create_series_msg(submission.shortlink)
        self.reddit.send_series_pm(submission, msg)

    def cache_activity_maybe(self, submission: praw.models.Submission) -> None:
        # only store activity if the post was created in the timelimit
        tl = self.cfg.post_timelimit
        now = int(time.time())
        if (diff := now - submission.created_utc) < tl:
            activity = Activity(
                author=submission.author.name,
                subreddit=submission.subreddit.display_name,
                last_post_id=submission.id,
                last_post_time=submission.created_utc
            )
            ttl = tl - int(diff)
            logger.info("Caching activity", info=activity, ttl=ttl)
            self.activity_db.persist(activity.author, activity, ttl=ttl)
        else:
            logger.info("Not caching activity for post outside timelimit",
                        author=submission.author.name,
                        subreddit=submission.subreddit.display_name,
                        id=submission.id)

    def process_previous(self):
        # for all submissions, check to see if any of them should be rejected
        # based on the time limit.
        # Get all recent submissions and then sort them into ascending order
        # As each submission is processed, check it against a user's new posts
        # in descending posted order
        posts = sorted(
            self.reddit.search_recent_posts(),
            key=attrgetter("created_utc")
        )

        logger.info(
            "Processing previous posts from last hour",
            subreddit=self.reddit.subreddit_name(),
            posts_found=len(posts)
        )

        cached_res = self.post_db.get_many([p.id for p in posts])

        for p, cached in zip(posts, cached_res):
            if not cached:
                logger.info("Skipping unprocessed post", submission=p.id)
                continue

            # if we already have a submission in storage, we care about:
            # 1. Checking if the submission isn't marked as 'series'
            # 2. If it hasn't been, check if the post is a 'series' flair
            # 3. If it is a series, then update the series property
            # 4. And then we want to send PMs
            logger.debug(
                "Processing previously seen submission",
                post_id=p.id,
                author=p.author.name
            )
            # Do processing on previous submissions to see if we need to
            # add the series message if we saw this before and it's not a
            # series but then later flaired as one, send the message
            if not cached.series:
                try:
                    if p.link_flair_css_class.lower() == self.cfg.series_flair_name.lower():
                        logger.info(
                            "Post was flaired 'Series' after the fact. Posting message",
                            post_id=p.id
                        )

                        self.post_series_reminder(p)
                        self.send_series_pm(p)

                        cached.series = True
                        cached.sent_series_pm = True
                        self.post_db.update(cached.id, cached)
                except AttributeError:
                    pass

    def fetch_new(self) -> None:
        """This method uses the subreddit/new API to get new submissions.
        /new has submissions immediately upon posting, so this endpoint is
        better for retrieving posts immediately, as /search incurs a time
        delay due to indexing."""
        listing = sorted(
            self.reddit.retrieve_new_posts(before=self.latest_post),
            key=attrgetter("created_utc")
        )
        cached_res = self.post_db.get_many([s.id for s in listing])
        for s, cached in zip(listing, cached_res):
            if cached:
                logger.debug("Skipping previously seen post", submission=s.id)
                continue

            # prevention for issue 102
            if s.subreddit.display_name != self.reddit.subreddit_name():
                logger.warn("Found post from other subreddit!",
                            subreddit=s.subreddit.display_name,
                            submission=s.id)
                continue

            # filter for issue 119
            if self.cfg.ignore_old_posts:
                now = int(time.time())
                if (now - s.created_utc) > self.cfg.ignore_older_than:
                    logger.info("Ignoring older /new post",
                                submission=s.id)
                    continue

            sub = Submission(
                id=s.id,
                author=s.author.name,
                submitted=s.created_utc
            )
            extra_log: dict[str, Any] = {}

            if self.reject_by_timelimit(s):
                sub.deleted = True
            else:
                # Here we want all the formatting and tag issues
                meta = self.analyzer.analyze(s)
                extra_log["invalid_tags"] = meta.invalid_tags
                extra_log["has_nsfw_title"] = meta.has_nsfw_title
                extra_log["has_codeblocks"] = meta.has_codeblocks
                extra_log["has_long_paragraphs"] = meta.has_long_paragraphs
                extra_log["series_finale"] = meta.is_final

                if meta.is_invalid():
                    # We have bad (tags|title) - Delete post and send PM.
                    msg = self.prepare_delete_message(s, meta)
                    self.reddit.add_comment(
                        s,
                        msg,
                        distinguish=True,
                        sticky=True
                    )
                    self.reddit.delete_post(s)
                    sub.deleted = True
                else:
                    # this post is valid, cache the activity
                    # data
                    self.cache_activity_maybe(s)

                    if meta.is_serial():
                        # set the series flair for this post
                        self.reddit.set_series_flair(
                            s, name=self.series_flair_name
                        )
                        sub.series = True

                        # don't send PMs if this is final
                        if not meta.is_final:
                            self.post_series_reminder(s)
                            self.send_series_pm(s)
                            sub.sent_series_pm = True

            if not sub.deleted:
                # this needs to not be set to a deleted post because
                # using the 'before' param with a deleted post returns
                # empty results
                self.latest_post = s

            logger.info(
                "Processed post",
                submission=json.loads(sub.json()),
                **extra_log
            )
            self.post_db.persist(sub.id, sub, ttl=self.cache_ttl)

    def run(self, forever: bool = False, interval: int = 15):
        """Run the autobot to find posts. Can be specified to run `forever`
        at `interval` seconds per run."""
        bot_start_time = time.time()
        while True:
            self.fetch_new()
            self.process_previous()

            if not forever:
                break

            run_interval = (time.time() - bot_start_time) % float(interval)
            sleep_interval = interval - int(run_interval)

            logger.info(
                "Sleeping until next run.",
                sleep_seconds=sleep_interval
            )
            time.sleep(sleep_interval)
