from collections.abc import Iterable
from dataclasses import dataclass
from operator import attrgetter
from typing import Tuple
import itertools
import logging
import re
import time

from autobot.config import Settings
from autobot.models import Submission, SubmissionHandler
from autobot.util.messages.templater import MessageBuilder
from autobot.util.reddit_util import SubredditTool

import praw
import rollbar


logger = logging.getLogger("autobot")


def partition(cond, it):
    """Partition a list in twain based on cond."""
    x, y = itertools.tee(it)
    return itertools.filterfalse(cond, x), filter(cond, y)


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

    def categorize_tags(self, title: str) -> Tuple[bool, bool, Iterable[str]]:
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
                series = post.link_flair_text.lower() == self.series_flair
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
        hnd: SubmissionHandler,
        msg_builder: MessageBuilder
    ):
        self.cfg = cfg
        self.hnd = hnd
        self.msg_bld = msg_builder
        self.reddit = SubredditTool(cfg)

        logger.info(f"Development mode on? {self.cfg.development_mode}")
        logger.info(
            f"Moderating: {self.cfg.subreddit}. "
            f"Enforcing time limits? {self.cfg.enforce_timelimit}. "
            f"Time limit? {self.cfg.post_timelimit} seconds."
        )

    def reject_submission_by_timelimit(
        self,
        post: praw.models.Submission
    ) -> bool:
        """Determine if a submission should be removed based on a time-limit
        for submissions for a subreddit."""
        now = time.time()

        most_recent = min(
            self.reddit.get_redditor_posts(post.author),
            key=attrgetter("created_utc"),
            default=None
        )

        if most_recent and most_recent.id != post.id:
            allowed_when = most_recent.created_utc + self.cfg.post_timelimit
            if allowed_when > now:
                logger.info(
                    f"Rejecting submission {post.id} "
                    f"by /u/{post.author.name} due to time limit"
                )
                return True

        return False

    def gen_series_reminder(self, post: praw.models.Submission) -> str:
        q = {
            "to": "UpdateMeBot",
            "subject": "Subscribe",
            "message": ("SubscribeMe! "
                        f"/r/{self.reddit.subreddit_name()} /u/{post.author}")
        }
        sub_url = self.reddit.gen_compose_url(q)
        return self.msg_bld.create_series_comment(sub_url)

    def process_time_limit_message(self, post: praw.models.Submission) -> None:
        """Because it's hard to determine if something's actually been
        deleted, this has to just find the most recent posts by the user
        from the last day."""
        most_recent = min(
            self.reddit.get_redditor_posts(post.author),
            key=attrgetter("created_utc"),
            default=None
        )

        if most_recent:
            logger.info(
                f"Previous post by {post.author} was at: "
                f"{most_recent.created_utc}"
            )
            logger.info(
                f"Current post by {post.author} was at: "
                f"{post.created_utc}"
            )
            time_diff = post.created_utc - most_recent.created_utc
            time_to_next_post = self.cfg.post_timelimit - time_diff
            human_fmt = englishify_time(time_to_next_post)
            logger.info(f"Notify {post.author} to post again in {human_fmt}")

            msg = self.msg_bld.create_post_a_day_msg(
                human_fmt,
                self.reddit.create_modmail_link()
            )

            self.reddit.add_comment(post, msg, distinguish=True)
            self.reddit.delete_post(post)

    def prepare_delete_message(
        self,
        post: praw.models.Submission,
        post_meta: PostMetadata
    ) -> str:

        modmail_link = self.reddit.create_modmail_link()
        reapproval_link = self.reddit.create_modmail_link(
                "Please reapprove submission",
                self.msg_bld.create_approval_msg(post.shortlink)
        )

        perm_del = False

        if post_meta.invalid_tags or post_meta.has_nsfw_title:
            perm_del = True

        return self.msg_bld.create_deleted_post_msg(
            post.shortlink,
            modmail_link=modmail_link,
            reapproval_modmail=reapproval_link,
            permanent=perm_del,
            has_nsfw_title=post_meta.has_nsfw_title,
            has_codeblocks=post_meta.has_codeblocks,
            long_paragraphs=post_meta.has_long_paragraphs,
            invalid_tags=post_meta.bad_tags()
        )

    def process_posts(self, restrict_to_sub: bool = True):
        cache_ttl = self.cfg.post_timelimit * 2

        # for all submissions, check to see if any of them should be rejected
        # based on the time limit.
        # Get all recent submissions and then sort them into ascending order
        # As each submission is processed, check it against a user's new posts
        # in descending posted order
        posts = sorted(
            self.reddit.get_recent_posts(),
            key=attrgetter("created_utc")
        )

        logger.info(
            f"Found {len(posts)} submissions in "
            f"/r/{self.reddit.subreddit_name()} from the last hour.")

        # prevent issue 102 from happening
        if restrict_to_sub:
            bad, posts = partition(
                lambda _: _.subreddit.display_name == self.reddit.subreddit_name(),
                posts
            )
            inv = " ".join((f"{p.subreddit.display_name}/{p.id}" for p in bad))
            if inv:
                logger.warn(f"Search returned posts from other subs! {inv}")

        analyzer = PostAnalyzer(self.cfg.series_flair_name)
        for p in posts:
            logger.info("Processing submission {0}.".format(p.id))

            post_series_comment = False
            if sub := self.hnd.get(p.id):
                logger.info(
                    f"Submission {p.id} was previously processed. "
                    "Doing previous submission checks."
                )
                # Do processing on previous submissions to see if we need to
                # add the series message if we saw this before and it's not a
                # series but then later flaired as one, send the message
                if not sub.series:
                    try:
                        if (p.link_flair_text.lower() == self.cfg.series_flair_name.lower()):
                            logger.info(
                                f"Submission {p.id} was flaired 'Series' "
                                "after the fact. Posting series message."
                            )
                            sub.series = True
                            post_series_comment = True
                            self.hnd.update(sub)
                    except AttributeError:
                        pass
            else:
                sub = Submission(
                    id=p.id,
                    author=p.author.name,
                    submitted=p.created_utc
                )

                if (self.cfg.enforce_timelimit and
                        self.reject_submission_by_timelimit(p)):
                    self.process_time_limit_message(p)
                    sub.deleted = True
                else:
                    # Here we want all the formatting and tag issues
                    meta = analyzer.analyze(p)
                    if meta.is_invalid():
                        # We have bad (tags|title) - Delete post and send PM.
                        if meta.invalid_tags:
                            logger.info(f"Bad tags found: {meta.invalid_tags}")
                        if meta.has_nsfw_title:
                            logger.info("Title issues found")
                        msg = self.prepare_delete_message(p, meta)
                        self.reddit.add_comment(
                            p,
                            msg,
                            distinguish=True,
                            sticky=True
                        )
                        self.reddit.delete_post(p)
                        sub.deleted = True
                    elif meta.is_serial():
                        # don't send PMs if this is final
                        if not meta.is_final:
                            # We have series tags in place. Send a PM
                            logger.info("Series tags found, sending PM.")
                            self.reddit.send_series_pm(
                                p,
                                self.msg_bld.create_series_msg(p.shortlink)
                            )
                            # Post the remindme bot message
                            post_series_comment = True
                            sub.sent_series_pm = True

                        # set the series flair for this post
                        self.reddit.set_series_flair(p)
                        sub.series = True

                if post_series_comment:
                    series_comment = self.gen_series_reminder(p)
                    self.reddit.post_series_reminder(p, series_comment)

                logger.info(
                    f"Caching metadata for submission {p.id} "
                    f"for {cache_ttl} seconds"
                )
                self.hnd.persist(sub, ttl=cache_ttl)

    def run(self, forever: bool = False, interval: int = 300):
        """Run the autobot to find posts. Can be specified to run `forever`
        at `interval` seconds per run."""

        bot_start_time = time.time()

        while True:
            try:
                self.process_posts()
            except Exception:
                logger.exception("bot:run")
                rollbar.report_exc_info()

            if not forever:
                break

            run_interval = (time.time() - bot_start_time) % float(interval)
            sleep_interval = float(interval) - run_interval

            logger.info(f"Sleeping {sleep_interval} seconds until next run.")
            time.sleep(sleep_interval)
