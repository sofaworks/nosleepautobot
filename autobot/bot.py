#!/usr/bin/env python

from collections.abc import Iterable, Iterator, Mapping
from collections import namedtuple
from operator import attrgetter
import itertools
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from autobot.config import Settings
from autobot.models import Submission, SubmissionHandler
from autobot.util.messages.templater import MessageBuilder

import praw
import rollbar

PrawSubmissionIter = Iterator[praw.models.Submission]

logger = logging.getLogger("autobot")


class MissingFlairException(Exception):
    """Custom exception class when a flair doesn't exist."""
    ...


FormattingIssues = namedtuple(
    'FormattingIssues',
    ['long_paragraphs', 'has_codeblocks']
)
TitleIssues = namedtuple('TitleIssues', ['title_contains_nsfw'])


def partition(cond, it):
    """Partition a list in twain based on cond."""
    x, y = itertools.tee(it)
    return itertools.filterfalse(cond, x), filter(cond, y)


def check_valid_title(title):
    """Checks if the title contains valid content"""
    title_issues = TitleIssues(title_contains_nsfw=title_contains_nsfw(title))
    return title_issues


def categorize_tags(title: str) -> Mapping[str, Iterable[str]]:
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

    tag_cats: Mapping[str, list[str]] = {
        "valid_tags": [],
        "invalid_tags": []
    }

    # this regex might be a little too heavy-handed but it does support the valid tag formats
    allowed_tag_values = re.compile(r"^(?:(?:vol(?:\.|ume)?|p(?:ar)?t|pt\.)?\s?(?:[1-9][0-9]?|one|two|three|five|ten|eleven|twelve|fifteen|(?:(?:four|six|seven|eight|nine)(?:teen)?))|finale?|update(?:[ ]#?[0-9]*)?)$")
    matches = [m.group() for m in re.finditer(r"\[([^]]*)\]|\((.*?)\)|\{(.*?)\}|\|(.*?)\|", title)]
    # for each match check if it's in the accepted list of tags

    for m in matches:
        # remove the braces/brackets/parens
        text = m.lower()[1:-1].strip()
        if not allowed_tag_values.match(text):
            tag_cats['invalid_tags'].append(text)
        else:
            tag_cats['valid_tags'].append(text)

    return tag_cats


def englishify_time(seconds: int) -> str:
    """Converts seconds into a string describing how long it is in
    readable time."""
    hours, minutes = divmod(seconds, 3600)
    minutes, seconds = divmod(minutes, 60)

    return f"{hours} hours, {minutes} minutes, {seconds} seconds"


def paragraphs_too_long(
    paragraphs: Iterable[str],
    max_word_count: int = 350
) -> bool:
    for p in paragraphs:
        if max_word_count < len(re.findall(r'\w+', p)):
            return True
    return False


def title_contains_nsfw(title: str | None) -> bool:
    if not title:
        return False
    remap_chars = '{}[]()|.!?$*@#'
    exclude_map = {
        ord(c): ord(t) for c, t in zip(remap_chars, ' ' * len(remap_chars))
    }
    parts = title.lower().translate(exclude_map).split(' ')
    return any('nsfw' == x.strip() for x in parts)


def contains_codeblocks(paragraphs: Iterable[str]) -> bool:
    for _, p in enumerate(paragraphs):
        # this determines if the line is not just all whitespace and then
        # whether or not it contains the 4 spaces or tab characters, which
        # will trigger markdown <code> blocks
        if p.strip() and (p.startswith('    ') or p.lstrip(' ').startswith('\t')):
            return True
    return False


def collect_formatting_issues(post_body: str) -> FormattingIssues:
    # split the post body by paragraphs
    # Things that are considered 'paragraphs' are:
    # * A newline followed by some arbitrary number of spaces
    #   followed by a newline
    # * At least two instances of whitespace followed by a newline
    paragraphs = re.split(r'(?:\n\s*\n|[ \t]{2,}\n|\t\n)', post_body)
    return FormattingIssues(
            paragraphs_too_long(paragraphs),
            contains_codeblocks(paragraphs))


class SubredditTool:
    def __init__(self, cfg: Settings) -> None:
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
        logger.info("Retrieving submissions from the last hour")
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
                logger.info(
                    f"Problem sending series message to {post.author.name}: "
                    f"{repr(e)}"
                )
        else:
            logger.info("Running in DEVELOPMENT MODE - not PMing series msg")

    def post_series_reminder(
        self,
        post: praw.models.Submission,
        comment: str
    ) -> None:
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
            logger.info("Running in DEVELOPMENT MODE - not deleting post")

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
            logger.info(
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
            logger.info("Running in DEVELOPMENT MODE - not flairing post")

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
        formatting_issues: FormattingIssues,
        invalid_tags: Iterable[str],
        title_issues: TitleIssues
    ) -> str:

        modmail_link = self.reddit.create_modmail_link()
        reapproval_link = self.reddit.create_modmail_link(
                "Please reapprove submission",
                self.msg_bld.create_approval_msg(post.shortlink)
        )

        perm_del = False

        if invalid_tags or any(title_issues):
            perm_del = True

        return self.msg_bld.create_deleted_post_msg(
            post.shortlink,
            modmail_link=modmail_link,
            reapproval_modmail=reapproval_link,
            permanent=perm_del,
            has_nsfw_title=title_issues.title_contains_nsfw,
            has_codeblocks=formatting_issues.has_codeblocks,
            long_paragraphs=formatting_issues.long_paragraphs,
            invalid_tags=", ".join(invalid_tags)
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
            key=attrgetter('created_utc')
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
                if not sub.series and p.link_flair_text == 'Series':
                    logger.info(
                        f"Submission {p.id} was flaired 'Series' after the "
                        "fact. Posting series message."
                    )
                    sub.series = True
                    post_series_comment = True
                    self.hnd.update(sub)
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
                    formatting_issues = collect_formatting_issues(p.selftext)
                    title_issues = check_valid_title(p.title)
                    post_tags = categorize_tags(p.title)

                    if (post_tags['invalid_tags']
                            or any(title_issues)
                            or any(formatting_issues)):
                        # We have bad (tags|title) - Delete post and send PM.
                        if post_tags['invalid_tags']:
                            logger.info(f"Bad tags found: {post_tags['invalid_tags']}")
                        if any(title_issues):
                            logger.info("Title issues found")
                        msg = self.prepare_delete_message(
                                p,
                                formatting_issues,
                                post_tags['invalid_tags'],
                                title_issues
                        )
                        self.reddit.add_comment(
                                p,
                                msg,
                                distinguish=True,
                                sticky=True
                        )
                        self.reddit.delete_post(p)
                        sub.deleted = True
                    elif post_tags['valid_tags']:
                        tags = [tag.lower() for tag in post_tags["valid_tags"]]
                        if 'final' in tags:
                            # This was the final story, so don't make a post
                            # or send a PM
                            logger.info("Final tag found, not posting/DMing.")
                        else:
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
                    else:
                        # We had no tags at all.
                        logger.info("No tags found in post title.")

                        # Check if this submission has flair
                        if p.link_flair_text == 'Series':
                            sub.series = True
                            post_series_comment = True

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
