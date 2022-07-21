#!/usr/bin/env python

from collections.abc import Iterable, Iterator, Mapping
from collections import namedtuple
from operator import attrgetter
from string import Template
import itertools
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from autobot.models import Submission, SubmissionHandler
from autobot.config import Settings

import praw
import rollbar

PrawSubmissionIter = Iterator[praw.models.Submission]


class MissingFlairException(Exception):
    """Custom exception class when a flair doesn't exist."""
    ...


FormattingIssues = namedtuple('FormattingIssues', ['long_paragraphs', 'has_codeblocks'])
TitleIssues = namedtuple('TitleIssues', ['title_contains_nsfw'])


POST_A_DAY_MESSAGE = Template('Hi there! /r/nosleep limits posts to one post per author per day, '
                      'in order to give all submitters here an equal shot at the front page.\n\n'
                      'As such, your post has been removed. Feel free to repost your story '
                      'in **${time_remaining}**.\n\n'
                      'Confused? See the [mod announcement](http://www.reddit.com/r/NoSleepOOC/comments/1m1spe/rule_addition_one_days_spacing_between_nosleep/) '
                      'on the subject for more information. If you believe your post was removed in error, please '
                      '[message the moderators](http://www.reddit.com/message/compose?to=%2Fr%2Fnosleep).'
                      )

PERMANENT_REMOVED_POST_HEADER = Template('Hi there! [Your post](${post_url}) has been removed from /r/nosleep '
                                    'for violating the following rules:')

TEMPORARY_REMOVED_POST_HEADER = Template('Hi there! [Your post](${post_url}) has been **temporarily** '
                                    'removed from /r/nosleep due to the following formatting issues '
                                    'detected in your post:')

DISALLOWED_TAGS_MESSAGE = ('\n\n* **Invalid Tags**\n\n'
                           '  /r/nosleep has strict rules about tags in story titles:\n\n'
                           '  **Tags (example: [True], [real experience]) are not allowed.** '
                           'The only thing in brackets **[]**, **{}** or parenthesis **()** '
                           'should be a reference to which "part" of your series the post is. '
                           '**Example**: (part 1) or [Pt2].')

NSFW_TITLE_MESSAGE = ('\n\n* **Title contains "NSFW"**\n\n'
                      '  Your post title appears to include **NSFW** in the title. /r/nosleep '
                      'does not allow **NSFW** to be stated in the title of stories. Stories '
                      'can be marked **NSFW** after they are posted by click **NSFW** or **Add Trigger Warning** '
                      '(depending on your UI) at the bottom of the post.')

REPOST_MESSAGE = '\n\n**Since titles cannot be edited on Reddit, please repost your story with a corrected title.**\n\n'

ADDITIONAL_FORMATTING_MESSAGE = ('\n\nAdditionally, the following issues have been detected in your post, '
                                 'which either violate rules or may make your post unreadable.'
                                 ' Please correct them when re-posting your story.')


SERIES_MESSAGE = Template('Hi there! It looks like you are writing an /r/nosleep series! '
                  'Awesome! Please be sure to double-check that [your post](${post_url}) '
                  'has "series" flair and please remember to include a link '
                  'to the previous part at the top of your story.\n\n'
                  "Don't know how to add flair? Visit your story's comment page "
                  'and look underneath the post itself. Click on the **flair** button '
                  'to bring up a list of options. Choose the "series" option and hit "save"!')

LONG_PARAGRAPH_MESSAGE= ('\n\n* **Long Paragraphs Detected**\n\n'
                         '  You have one or more paragraphs containing more than 350 words. '
                         'Please break up your story into smaller paragraphs. You can create paragraphs '
                         'by pressing `Enter` twice at the end of a line.')

CODEBLOCK_MESSAGE = ('\n\n* **Paragraph with 4 (or more) Starting Spaces Detected**\n\n'
                     '  You have one or more paragraphs beginning with a tab or four or more spaces.\n\n'
                     '  On Reddit, lines beginning with a tab or four or more spaces are treated as '
                     'blocks of code and make your story unreadable. Please remove tabs or spaces at the beginning '
                     'of paragraphs/lines. You can create paragraphs by pressing `Enter` twice at the end '
                     'of a line if you haven\'t already done so.')

FORMATTING_CLOSE = Template('\n\n**Once you have fixed your formatting issues, please [click here](${modmail_link}) to request reapproval.** '
                    'The re-approval process is manual, so send a single request only. Multiple requests '
                    'do not mean faster approval; in fact they will clog the modqueue and result in '
                    're-approvals taking even more time.')

BOT_DESCRIPTION = Template('\n\n_I am a bot, and this was automatically posted. '
                    'Do not reply to me as messages will be ignored. '
                    'Please [contact the moderators of this subreddit](${subreddit_mail_uri}) '
                    'if you have any questions, concerns, or bugs to report._')


def partition(cond, it):
    """Partition a list in twain based on cond."""
    x, y = itertools.tee(it)
    return itertools.filterfalse(cond, x), filter(cond, y)


def generate_reapproval_message(post_url):
    return ('[My post]({0}) to /r/NoSleep was removed for '
            'formatting issues. I have fixed those issues and '
            'am now requesting re-approval.'
            '\n\n_Note to moderation team: if this story is '
            'eligible for re-approval, remember to remove '
            'the bot\'s comment from it._'.format(post_url))


def generate_modmail_link(subreddit, subject=None, message=None):
    base_url = 'https://www.reddit.com/message/compose?'
    query = {
                'to': '/r/{0}'.format(subreddit),
            }

    if subject:
        query['subject'] = subject

    if message:
        query['message'] = message

    urllib.parse.urlencode(query)
    return base_url + urllib.parse.urlencode(query)


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
    allowed_tag_values = re.compile("^(?:(?:vol(?:\.|ume)?|p(?:ar)?t|pt\.)?\s?(?:[1-9][0-9]?|one|two|three|five|ten|eleven|twelve|fifteen|(?:(?:four|six|seven|eight|nine)(?:teen)?))|finale?|update(?:[ ]#?[0-9]*)?)$")
    matches = [m.group() for m in re.finditer("\[([^]]*)\]|\((.*?)\)|\{(.*?)\}|\|(.*?)\|", title)]
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
    """Converts seconds into a string describing how long it is in hours/minutes/seconds"""
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
    exclude_map = {ord(c): ord(t) for c, t in zip(remap_chars, ' ' * len(remap_chars))}
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
    # * A newline followed by some arbitrary number of spaces followed by a newline
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
        logging.info("Retrieving submissions from the last hour")
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

    def delete_post(self, post: praw.models.Submission) -> None:
        if not self.read_only:
            post.mod.remove()
        else:
            logging.info("Running in DEVELOPMENT MODE - not deleting post")

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
            logging.info("Running in DEVELOPMENT MODE - not adding comment")

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
            logging.info("Running in DEVELOPMENT MODE - not flairing post")


class AutoBot:
    def __init__(self, cfg: Settings, hnd: SubmissionHandler):
        self.cfg = cfg
        self.hnd = hnd
        self.reddit = SubredditTool(cfg)

        logging.info(f"Development mode on? {self.cfg.development_mode}")
        logging.info(
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
                logging.info(
                    f"Rejecting submission {post.id} "
                    f"by /u/{post.author.name} due to time limit"
                )
                return True

        return False

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
            logging.info(f"Previous post by {post.author} was at: {most_recent.created_utc}")
            logging.info(f"Current post by {post.author} was at: {post.created_utc}")
            time_to_next_post = self.cfg.post_timelimit - (post.created_utc - most_recent.created_utc)
            human_fmt = englishify_time(time_to_next_post)
            logging.info(f"Notifying {post.author} to post again in {human_fmt}")

            components = [
                POST_A_DAY_MESSAGE.safe_substitute(time_remaining=human_fmt),
                BOT_DESCRIPTION.safe_substitute(
                    subreddit_mail_uri=generate_modmail_link(
                        self.reddit.subreddit_name
                    )
                )
            ]

            fmt_msg = ''.join(components)

            self.reddit.add_comment(post, fmt_msg, distinguish=True)
            self.reddit.delete_post(post)

    def post_series_reminder(self, post: praw.models.Submission) -> None:
        series_message = "It looks like there may be more to this story. Click [here]({}) to get a reminder to check back later. Got issues? Click [here]({})."

        message_url = "https://www.reddit.com/message/compose/?to=UpdateMeBot&subject=Subscribe&message=SubscribeMe%21%20%2Fr%2Fnosleep%20%2Fu%2F{}".format(str(post.author))
        issues_url = "https://www.reddit.com/r/nosleep/wiki/nosleepautobot"

        msg = series_message.format(message_url, issues_url)
        self.reddit.add_comment(
            post,
            msg,
            distinguish=True,
            sticky=True,
            lock=True
        )

    def prepare_delete_message(
        self,
        post: praw.models.Submission,
        formatting_issues,
        invalid_tags,
        title_issues
    ) -> str:
        final_message = []
        if invalid_tags or any(title_issues):
            final_message.append(PERMANENT_REMOVED_POST_HEADER.safe_substitute(post_url=post.shortlink))
            if invalid_tags: final_message.append(DISALLOWED_TAGS_MESSAGE)
            if title_issues.title_contains_nsfw: final_message.append(NSFW_TITLE_MESSAGE)
            final_message.append(REPOST_MESSAGE)
            if any(formatting_issues):
                final_message.append(ADDITIONAL_FORMATTING_MESSAGE)

                if formatting_issues.long_paragraphs:
                    final_message.append(LONG_PARAGRAPH_MESSAGE)
                if formatting_issues.has_codeblocks:
                    final_message.append(CODEBLOCK_MESSAGE)
        else:
            if any(formatting_issues):
                modmail_link = generate_modmail_link(self.reddit.subreddit_name,
                                                     'Please reapprove submission',
                                                     generate_reapproval_message(post.shortlink))

                final_message.append(TEMPORARY_REMOVED_POST_HEADER.safe_substitute(post_url=post.shortlink))

                if formatting_issues.long_paragraphs:
                    final_message.append(LONG_PARAGRAPH_MESSAGE)
                if formatting_issues.has_codeblocks:
                    final_message.append(CODEBLOCK_MESSAGE)
                final_message.append(FORMATTING_CLOSE.safe_substitute(modmail_link=modmail_link))

        final_message.append(BOT_DESCRIPTION.safe_substitute(
            subreddit_mail_uri=generate_modmail_link(self.reddit.subreddit_name)))

        return ''.join(final_message)

    def process_posts(self, restrict_to_sub: bool = True):
        cache_ttl = self.cfg.post_timelimit * 2

        # for all submissions, check to see if any of them should be rejected based on the time limit
        # Get all recent submissions and then sort them into ascending order
        # As each submission is processed, check it against a user's new posts in descending posted order
        posts = sorted(self.reddit.get_recent_posts(), key=attrgetter('created_utc'))

        logging.info(f"Found {len(posts)} submissions in /r/{self.reddit.subreddit_name()} from the last hour.")

        # prevent issue 102 from happening
        if restrict_to_sub:
            bad, posts = partition(lambda _: _.subreddit.display_name == self.reddit.subreddit_name(), posts)
            inv = " ".join((f"{p.subreddit.display_name}/{p.id}" for p in bad))
            if inv:
                logging.warn(f"Search returned posts from other subs! {inv}")

        for p in posts:
            logging.info("Processing submission {0}.".format(p.id))

            if sub := self.hnd.get(p.id):
                logging.info("Submission {0} was previously processed. Doing previous submission checks.".format(p.id))
                # Do processing on previous submissions to see if we need to add the series message
                # if we saw this before and it's not a series but then later flaired as one, send
                # the message
                if not sub.series and p.link_flair_text == 'Series':
                    logging.info("Submission {0} was flaired 'Series' after the fact. Posting series message.".format(p.id))
                    sub.series = True
                    self.post_series_reminder(p)
                    self.hnd.update(sub)
            else:
                sub = Submission(
                    id=p.id,
                    author=p.author.name,
                    submitted=p.created_utc
                )

                if self.cfg.enforce_timelimit and self.reject_submission_by_timelimit(p):
                    self.process_time_limit_message(p)
                    sub.deleted = True
                else:
                    # Here we want all the formatting and tag issues
                    formatting_issues = collect_formatting_issues(p.selftext)
                    title_issues = check_valid_title(p.title)
                    post_tags = categorize_tags(p.title)

                    if post_tags['invalid_tags'] or any(title_issues) or any(formatting_issues):
                        # We have bad tags or a bad title! Delete post and send PM.
                        if post_tags['invalid_tags']: logging.info("Bad tags found: {0}".format(post_tags['invalid_tags']))
                        if any(title_issues): logging.info("Title issues found")
                        msg = self.prepare_delete_message(p, formatting_issues, post_tags['invalid_tags'], title_issues)
                        self.reddit.add_comment(p, msg, distinguish=True, sticky=True)
                        self.reddit.delete_post(p)
                        sub.deleted = True
                    elif post_tags['valid_tags']:
                        if 'final' in (tag.lower() for tag in post_tags['valid_tags']):
                            # This was the final story, so don't make a post or send a PM
                            logging.info("Final tag found, not sending PM/posting")
                        else:
                            # We have series tags in place. Send a PM
                            logging.info("Series tags found")
                            try:
                                p.author.message("Reminder about your series post on r/nosleep", SERIES_MESSAGE.safe_substitute(post_url=p.shortlink), None)
                            except Exception as e:
                                logging.info("Problem sending message to {}: {}".format(p.author.name, repr(e)))
                            # Post the remindme bot message
                            self.post_series_reminder(p)
                            sub.sent_series_pm = True

                        # set the series flair for this post
                        self.reddit.set_series_flair(p)
                        try:
                            self.reddit.set_series_flair(p)
                        except Exception as e:
                            logging.exception("Unexpected problem setting flair for {0}: {1}".format(p.id, str(e)))
                        sub.series = True
                    else:
                        # We had no tags at all.
                        logging.info("No tags found in post title.")

                        # Check if this submission has flair
                        if p.link_flair_text == 'Series':
                            sub.series = True
                            self.post_series_reminder(p)


                logging.info("Caching metadata for submission {0} for {1} seconds".format(p.id, cache_ttl))
                self.hnd.persist(sub, ttl=cache_ttl)


    def run(self, forever: bool = False, interval: int = 300):
        """Run the autobot to find posts. Can be specified to run `forever`
        at `interval` seconds per run."""

        bot_start_time = time.time()

        while True:
            try:
                self.process_posts()
            except Exception:
                logging.exception("bot:run")
                rollbar.report_exc_info()

            if not forever:
                break

            sleep_interval = float(interval) - ((time.time() - bot_start_time) % float(interval))

            logging.info(f"Sleeping for {sleep_interval} seconds until next run.")
            time.sleep(sleep_interval)
