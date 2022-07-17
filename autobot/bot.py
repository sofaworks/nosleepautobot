#!/usr/bin/env python

from collections.abc import Iterator
from collections import namedtuple
from operator import attrgetter
from string import Template
import itertools
import traceback
import urllib.parse
import argparse
import logging
import urllib.request, urllib.parse, urllib.error
import time
import sys
import re

from autobot.models import Submission, SubmissionHandler
from autobot.config import Settings

import praw
import redis
import rollbar

from rollbar.logger import RollbarHandler


class NoSuchFlairError(Exception):
    """Custom exception class when a flair doesn't exist."""
    pass


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


def create_argparser():
    parser = argparse.ArgumentParser(prog='bot.py')
    parser.add_argument('--forever', required=False, action='store_true', help='If specified, runs bot forever.')
    parser.add_argument('-i', '--interval', required=False, type=int, default=300, help='How many seconds to wait between bot execution cycles. Only used if "forever" is specified.')
    return parser


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


def categorize_tags(title):
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

    tag_cats = {'valid_tags': [], 'invalid_tags': []}

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


def englishify_time(seconds):
    '''Converts seconds  into a string describing how long it is in hours/minutes/seconds'''
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return '{0} hours, {1} minutes, {2} seconds'.format(int(hours), int(minutes), int(seconds))


def paragraphs_too_long(paragraphs, max_word_count=350):
    for p in paragraphs:
        if max_word_count < len(re.findall(r'\w+', p)):
            return True
    return False


def title_contains_nsfw(title):
    if not title: return False
    remap_chars = '{}[]()|.!?$*@#'
    exclude_map = {ord(c) : ord(t) for c, t in zip(remap_chars, ' ' * len(remap_chars))}
    parts = title.lower().translate(exclude_map).split(' ')
    return any('nsfw' == x.strip() for x in parts)


def contains_codeblocks(paragraphs):
    for _, p in enumerate(paragraphs):
        # this determines if the line is not just all whitespace and then
        # whether or not it contains the 4 spaces or tab characters, which
        # will trigger markdown <code> blocks
        if p.strip() and (p.startswith('    ') or p.lstrip(' ').startswith('\t')):
            return True
    return False


def collect_formatting_issues(post_body):
    # split the post body by paragraphs
    # Things that are considered 'paragraphs' are:
    # * A newline followed by some arbitrary number of spaces followed by a newline
    # * At least two instances of whitespace followed by a newline
    paragraphs = re.split(r'(?:\n\s*\n|[ \t]{2,}\n|\t\n)', post_body)
    return FormattingIssues(
            paragraphs_too_long(paragraphs),
            contains_codeblocks(paragraphs))


class AutoBot:
    def __init__(self, cfg: Settings, hnd: SubmissionHandler):
        self.cfg = cfg
        self.hnd = hnd
        self.reddit = praw.Reddit(
                user_agent=self.cfg.user_agent,
                client_id=self.cfg.client_id,
                client_secret=self.cfg.client_secret,
                username=self.cfg.reddit_username,
                password=self.cfg.reddit_password
        )
        self.subreddit = self.reddit.subreddit(self.cfg.subreddit)

        logging.info(f"Development mode on? {self.cfg.development_mode}")
        logging.info(f"Moderating: {0}. Enforcing time limits? {1}. Time limit? {2} seconds".format(
            self.subreddit.display_name,
            self.cfg.enforce_timelimit,
            self.cfg.post_timelimit
        ))

        if not self.subreddit.user_is_moderator:
            raise AssertionError(f"User {self.cfg.reddit_username} is not moderator of subreddit {self.subreddit.display_name}")

    def reject_submission_by_timelimit(self, submission):
        """Determine if a submission should be removed based on a time-limit
        for submissions for a subreddit."""

        now = int(time.time())

        # We get submissions in ascending order (so, oldest ones first from last hour).
        # We want to find the most recent post (as in the oldest timestamp)
        user_posts = self.get_last_subreddit_submissions(submission.author)

        try:
            most_recent = min(user_posts, key=lambda i: i.created_utc)
        except ValueError:
            # probably means user_posts was empty...which would be super weird.
            most_recent = None

        if most_recent and (most_recent.id != submission.id):
            next_post_allowed_time = most_recent.created_utc + self.cfg.post_timelimit
            if next_post_allowed_time > now:
                logging.info("Rejecting submission {0} by /u/{1} due to time limit".format(submission.id, submission.author.name))
                return True

        return False

    def get_recent_submissions(self) -> Iterator[praw.models.Submission]:
        """Get most recent submissions from the subreddit - right now it
        fetches the last hour's worth of results."""
        logging.info("Retrieving submissions from the last hour")
        posts = self.subreddit.search(
            f'subreddit:{self.subreddit.display_name}',
            time_filter='hour',
            syntax='lucene',
            sort='new'
        )
        return posts

    def get_last_subreddit_submissions(self, redditor, sort='new'):
        # Retrieve the data from the API of all the posts made by this author in the last 24 hours.
        # This has to be done via cloudsearch because Reddit apparently doesn't enable
        # semantic hyphening in their lucene indexes, so user names with hyphens in them
        # will return improper results.
        search_results = list(self.subreddit.search('author:"{0}"'.format(redditor.name), time_filter='day', syntax='cloudsearch', sort=sort))
        logging.info("Found {0} submissions by user {1} in /r/{2} in last 24 hours".format(
                         len(search_results), redditor.name, self.subreddit.display_name))
        return search_results

    def process_time_limit_message(self, submission):

        # Because it's hard to determine if something's actually been
        # deleted, this has to just find the most recent posts by the user
        # from the last day.
        user_posts = self.get_last_subreddit_submissions(submission.author)
        most_recent = min(user_posts, key=lambda i: i.created_utc)

        logging.info("Previous post by {0} was at: {1}".format(submission.author, most_recent.created_utc))
        logging.info("Current post by {0} was at: {1}".format(submission.author, submission.created_utc))
        time_to_next_post = self.cfg.post_timelimit - (submission.created_utc - most_recent.created_utc)

        logging.info("Notifying {0} to post again in {1}".format(submission.author, englishify_time(time_to_next_post)))

        components = [POST_A_DAY_MESSAGE.safe_substitute(time_remaining=englishify_time(time_to_next_post)),
                      BOT_DESCRIPTION.safe_substitute(subreddit_mail_uri=generate_modmail_link(self.subreddit.display_name))]

        fmt_msg = ''.join(components)

        mod_comment = submission.reply(fmt_msg)
        mod_comment.mod.distinguish()
        submission.mod.remove()


    def post_series_reminder(self, submission):
        series_message = "It looks like there may be more to this story. Click [here]({}) to get a reminder to check back later. Got issues? Click [here]({})."

        message_url = "https://www.reddit.com/message/compose/?to=UpdateMeBot&subject=Subscribe&message=SubscribeMe%21%20%2Fr%2Fnosleep%20%2Fu%2F{}".format(str(submission.author))
        issues_url = "https://www.reddit.com/r/nosleep/wiki/nosleepautobot"

        series_comment = series_message.format(message_url, issues_url)
        comment = submission.reply(series_comment)
        comment.mod.distinguish(sticky=True)
        comment.mod.lock()

    def set_submission_flair(self, submission, flair):
        """Set a flair for a submission."""
        for f in submission.flair.choices():
            if f['flair_css_class'].lower() == flair.lower():
                try:
                    submission.flair.select(f['flair_template_id'])
                    return
                except KeyError:
                    # Huh, that's weird, our flair doesn't have the key we expected
                    raise
        raise NoSuchFlairError("Flair class {0} not found for subreddit /r/{1}".format(flair, self.subreddit.display_name))

    def prepare_delete_message(self, post, formatting_issues, invalid_tags, title_issues):
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
                modmail_link = generate_modmail_link(self.subreddit.display_name,
                                                     'Please reapprove submission',
                                                     generate_reapproval_message(post.shortlink))

                final_message.append(TEMPORARY_REMOVED_POST_HEADER.safe_substitute(post_url=post.shortlink))

                if formatting_issues.long_paragraphs:
                    final_message.append(LONG_PARAGRAPH_MESSAGE)
                if formatting_issues.has_codeblocks:
                    final_message.append(CODEBLOCK_MESSAGE)
                final_message.append(FORMATTING_CLOSE.safe_substitute(modmail_link=modmail_link))

        final_message.append(BOT_DESCRIPTION.safe_substitute(
            subreddit_mail_uri=generate_modmail_link(self.subreddit.display_name)))

        return ''.join(final_message)

    def process_posts(self, restrict_to_sub: bool = True):
        cache_ttl = self.cfg.post_timelimit * 2

        # for all submissions, check to see if any of them should be rejected based on the time limit
        # Get all recent submissions and then sort them into ascending order
        # As each submission is processed, check it against a user's new posts in descending posted order
        posts = sorted(self.get_recent_submissions(), key=attrgetter('created_utc'))

        logging.info(f"Found {len(posts)} submissions in /r/{self.subreddit.display_name} from the last hour.")

        # prevent issue 102 from happening
        if restrict_to_sub:
            bad, posts = partition(lambda _: _.subreddit.display_name == self.subreddit.display_name, posts)
            inv  = ' '.join((f"{p.subreddit.display_name}/{p.id}" for p in bad))
            if inv:
                logging.warn(f"Search returned posts from other subs! {inv}")

        for p in posts:
            logging.info("Processing submission {0}.".format(p.id))
            if self.cfg.development_mode:
                logging.info("DEVELOPMENT MODE set. Not mutating post.")
                continue

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
                        message = self.prepare_delete_message(p, formatting_issues, post_tags['invalid_tags'], title_issues)
                        com = p.reply(message)
                        com.mod.distinguish()
                        p.mod.remove()
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
                        try:
                            self.set_submission_flair(p, flair='flair-series')
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

    def run(self, forever=False, interval=300):
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

            logging.info("Sleeping for {0} seconds until next run.".format(sleep_interval))
            time.sleep(sleep_interval)


def uncaught_ex_handler(ex_type, value, tb):
    logging.critical('Got an uncaught exception')
    logging.critical(''.join(traceback.format_tb(tb)))
    logging.critical('{0}: {1}'.format(ex_type, value))


def init_rollbar(token: str, environment: str) -> None:
    rollbar.init(token, environment)
    rollbar_handler = RollbarHandler()
    rollbar_handler.setLevel(logging.ERROR)
    logging.getLogger('').addHandler(rollbar_handler)


def transform_and_roll_out():
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
    bot = AutoBot(settings, hd)
    bot.run(args.forever, args.interval)


if __name__ == '__main__':
    transform_and_roll_out()
