#!/usr/bin/env python

from collections import namedtuple
from string import Template
import ConfigParser
import itertools
import traceback
import urlparse
import datetime
import argparse
import logging
import urllib
import signal
import string
import time
import sys
import os
import re

import rollbar
from rollbar.logger import RollbarHandler
import praw
from walrus import Walrus, Model, TextField, IntegerField, BooleanField
from praw.models.reddit.subreddit import SubredditModeration


USER_AGENT = 'user_agent'
REDDIT_USERNAME = 'reddit_username'
REDDIT_PASSWORD = 'reddit_password'
CLIENT_ID = 'client_id'
CLIENT_SECRET = 'client_secret'
POST_TIMELIMIT = 'seconds_between_posts'
SUBREDDIT = 'subreddit'
REDIS_BACKEND = 'redis_backend'
REDIS_URL = 'redis_url'
REDIS_PORT = 'redis_port'
REDIS_PASSWORD = 'redis_password'
ROLLBAR_ACCESS_TOKEN = 'rollbar_access_token'
ROLLBAR_ENVIRONMENT = 'rollbar_environment'


class NoSuchFlairError(Exception):
    """Custom exception class when a flair doesn't exist."""
    pass


class AutoBotBaseModel(Model):
    database = None
    namespace = 'autobot'

    @classmethod
    def set_database(cls, db):
        cls.database = db


class AutoBotSubmission(AutoBotBaseModel):
    submission_id = TextField(primary_key=True)
    author = TextField(index=True)
    submission_time = IntegerField()
    is_series = BooleanField()
    sent_series_pm = BooleanField()
    deleted = BooleanField()

    @classmethod
    def set_ttl(cls, submission, ttl=86400):
        submission.to_hash().expire(ttl=ttl)

    def set_index_ttls(self, ttl=86400):
        '''Kind of a hacky way to get index keys to expire since they
        are normally created without any TTL whatsoever.'''
        for mi in self._indexes:
            for index in mi.get_indexes():
                key = index.get_key(index.field_value(self)).key
                self.database.expire(key, ttl)


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



def create_argparser():
    parser = argparse.ArgumentParser(prog='bot.py')
    parser.add_argument('-c', '--conf', required=False, type=str, help='Configuration file to use for the bot')
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

    urllib.urlencode(query)
    return base_url + urllib.urlencode(query)


def check_valid_title(title):
    """Checks if the title contains valid content"""
    title_issues = TitleIssues(title_contains_nsfw=title_contains_nsfw(title))
    return title_issues


def categorize_tags(title):
    """Parses tags out of the post title
    Valid submission tags are things between [], {}, and ()

    Valid tag values are:

    * a single number (shorthand for part #)
    * Pt/Pt./Part + number (integral or textual)
    * Vol/Vol./Volume  + number (integral or textual)
    * Update
    * Final
    """

    tag_cats = {'valid_tags': [], 'invalid_tags': []}

    # this regex might be a little too heavy-handed but it does support the valid tag formats
    allowed_tag_values = re.compile("^(?:(?:vol(?:\.|ume)?|p(?:ar)?t|pt\.)?\s?(?:[1-9][0-9]?|one|two|three|five|ten|eleven|twelve|fifteen|(?:(?:four|six|seven|eight|nine)(?:teen)?))|final|update(?:[ ]#?[0-9]*)?)$")
    matches = [m.group() for m in re.finditer("\[([^]]*)\]|\((.*?)\)|\{(.*?)\}", title)]
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
    remap_chars = u'{}[]().!?$*@#'
    exclude_map = {ord(c) : ord(t) for c, t in zip(remap_chars, u' ' * len(remap_chars))}
    parts = title.lower().translate(exclude_map).split(' ')
    return any('nsfw' == x.strip() for x in parts)


def contains_codeblocks(paragraphs):
    for idx, p in enumerate(paragraphs):
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


def get_bot_defaults():
    """Returns some defaults for running the bot."""
    return {POST_TIMELIMIT: 86400,
            REDIS_BACKEND: 'redis',
            REDIS_URL: 'localhost',
            REDIS_PORT: 6379,
            REDIS_PASSWORD: None,
            ROLLBAR_ENVIRONMENT: 'staging'}


def parse_config(conf):
    '''conf is a file or file-like pointer'''
    config = ConfigParser.SafeConfigParser(allow_no_value=True)
    config.readfp(conf)

    settings = {
        REDDIT_USERNAME: config.get('autobot', 'user'),
        REDDIT_PASSWORD: config.get('autobot', 'password'),
        CLIENT_ID: config.get('autobot', 'client_id'),
        CLIENT_SECRET: config.get('autobot', 'client_secret'),
        POST_TIMELIMIT: config.getint('autobot', 'seconds_between_allowed_posts'),
        SUBREDDIT: config.get('autobot', 'subreddit'),
        REDIS_BACKEND: config.get('autobot', 'redis_backend'),
        REDIS_URL: config.get('autobot', 'redis_url'),
        REDIS_PORT: config.getint('autobot', 'redis_port'),
    }

    if config.has_option('autobot', 'rollbar_access_token'):
        settings[ROLLBAR_ACCESS_TOKEN] = config.get('autobot', 'rollbar_access_token')


    if config.has_option('autobot', 'rollbar_environment'):
        settings[ROLLBAR_ENVIRONMENT] = config.get('autobot', 'rollbar_environment')

    return settings


def get_environment_configuration():
    """Gets configurations specified in environment variables"""

    try:
        time_limit = int(os.getenv('AUTOBOT_POST_TIMELIMIT'))
    except TypeError:
        time_limit = None

    # if we're using Redis Labs
    redis_cloud_url = os.getenv('REDISCLOUD_URL')

    if redis_cloud_url:
        url = urlparse.urlparse(redis_cloud_url)
        redis_host = url.hostname
        redis_port = url.port
        redis_password = url.password
    else:
        redis_host = os.getenv('AUTOBOT_REDIS_URL')
        redis_port = os.getenv('AUTOBOT_REDIS_PORT')
        redis_password = None

    override = {
            REDDIT_USERNAME: os.getenv('AUTOBOT_REDDIT_USERNAME'),
            REDDIT_PASSWORD: os.getenv('AUTOBOT_REDDIT_PASSWORD'),
            SUBREDDIT: os.getenv('AUTOBOT_SUBREDDIT'),
            CLIENT_ID: os.getenv('AUTOBOT_CLIENT_ID'),
            CLIENT_SECRET: os.getenv('AUTOBOT_CLIENT_SECRET'),
            POST_TIMELIMIT: time_limit,
            REDIS_BACKEND: os.getenv('AUTOBOT_REDIS_BACKEND'),
            REDIS_URL: redis_host,
            REDIS_PORT: redis_port,
            REDIS_PASSWORD: redis_password,
            ROLLBAR_ACCESS_TOKEN: os.getenv('ROLLBAR_ACCESS_TOKEN'),
            ROLLBAR_ENVIRONMENT: os.getenv('ROLLBAR_ENVIRONMENT')
    }

    # remove all the 'None' valued things
    return {k: v for k, v in override.items() if v is not None}


class AutoBot(object):
    def __init__(self, configuration):
        self.time_between_posts = configuration[POST_TIMELIMIT]

        self.reddit = praw.Reddit(user_agent='/r/nosleep AutoBot v 1.0 (by /u/SofaAssassin)',
                client_id=configuration[CLIENT_ID],
                client_secret=configuration[CLIENT_SECRET],
                username=configuration[REDDIT_USERNAME],
                password=configuration[REDDIT_PASSWORD])

        self.subreddit = self.reddit.subreddit(configuration[SUBREDDIT])

        self.moderator = SubredditModeration(self.subreddit)

        self.time_limit_between_posts = configuration[POST_TIMELIMIT]

        if not self.subreddit.user_is_moderator:
            raise AssertionError("User {0} is not moderator of subreddit {1}".format(configuration[REDDIT_USERNAME], subreddit.display_name))

    def get_previous_submission_record(self, submission):
        try:
            post = AutoBotSubmission.get(AutoBotSubmission.submission_id == submission.id)
            return post
        except:
            return None

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
            next_post_allowed_time = most_recent.created_utc + self.time_limit_between_posts
            if next_post_allowed_time > now:
                logging.info("Rejecting submission {0} by /u/{1} due to time limit".format(submission.id, submission.author.name))
                return True

        return False

    def get_recent_submissions(self):
        """Get most recent submissions from the subreddit (right now it fetches the last hour's worth of results)."""
        logging.info("Retrieving submissions from the last hour")
        submissions = list(self.subreddit.search('subreddit:{0}'.format(self.subreddit.display_name), time_filter='hour', syntax='lucene', sort='new'))
        logging.info("Found {0} submissions in /r/{1} from the last hour.".format(len(submissions), self.subreddit.display_name))
        return submissions

    def get_last_subreddit_submissions(self, redditor, sort='new'):
        # Retrieve the data from the API of all the posts made by this author in the last 24 hours.
        # This has to be done via cloudsearch because Reddit apparently doesn't enable
        # semantic hyphening in their lucene indexes, so user names with hyphens in them
        # will return improper results.
        search_results = list(self.subreddit.search("author:'{0}'".format(redditor.name), time_filter='day', syntax='cloudsearch', sort=sort))
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
        time_to_next_post = self.time_limit_between_posts - (submission.created_utc - most_recent.created_utc)

        logging.info("Notifying {0} to post again in {1}".format(submission.author, englishify_time(time_to_next_post)))

        components = [POST_A_DAY_MESSAGE.safe_substitute(time_remaining=englishify_time(time_to_next_post)),
                      BOT_DESCRIPTION.safe_substitute(subreddit_mail_uri=generate_modmail_link(self.subreddit.display_name))]

        fmt_msg = ''.join(components)

        self.moderator.distinguish(submission.reply(fmt_msg))
        self.moderator.remove(submission)


    def post_series_reminder(self, submission):
        series_message = "It looks like there may be more to this story. Click [here]({}) to get a reminder to check back later. Comment replies will be ignored by me."

        message_url = "https://www.reddit.com/message/compose/?to=UpdateMeBot&subject=Subscribe&message=SubscribeMe%21%20%2Fr%2Fnosleep%20%2Fu%2F{}".format(str(submission.author))

        series_comment = series_message.format(message_url)
        comment = submission.reply(series_comment)
        comment.mod.distinguish(sticky=True)


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


    def process_posts(self):
        cache_ttl = self.time_limit_between_posts * 2

        # for all submissions, check to see if any of them should be rejected based on the time limit
        # Get all recent submissions and then sort them into ascending order
        # As each submission is processed, check it against a user's new posts in descending posted order
        recents = sorted(self.get_recent_submissions(), key=lambda x: x.created_utc)
        logging.info("Processing submissions: {0}".format(recents))
        for s in recents:
            # temporary measure because of The Purge
            if s.link_flair_text == 'The Purge':
                logging.info("Submission {0} was ignored because it was part of 'The Purge'".format(s.id))
                continue
                
            logging.info("Processing submission {0}.".format(s.id))
            obj = self.get_previous_submission_record(s)
            if obj:
                logging.info("Submission {0} was previously processed. Doing previous submission checks.".format(s.id))
                # Do processing on previous submissions to see if we need to add the series message
                # if we saw this before and it's not a series but then later flaired as one, send
                # the message
                if not obj.is_series and (s.link_flair_text == 'Series'):
                    logging.info("Submission {0} was flaired 'Series' after the fact. Posting series message.".format(s.id))
                    obj.is_series = True
                    self.post_series_reminder(s)
                    obj.save()
            else:
                obj = AutoBotSubmission(
                        submission_id=s.id,
                        author=s.author.name,
                        submission_time=int(s.created_utc),
                        is_series=False,
                        sent_series_pm=False,
                        deleted=False)

                if self.reject_submission_by_timelimit(s):
                    self.process_time_limit_message(s)
                    obj.deleted = True
                else:
                    # Here we want all the formatting and tag issues
                    formatting_issues = collect_formatting_issues(s.selftext)
                    title_issues = check_valid_title(s.title)
                    post_tags = categorize_tags(s.title)

                    if post_tags['invalid_tags'] or any(title_issues) or any(formatting_issues):
                        # We have bad tags or a bad title! Delete post and send PM.
                        if post_tags['invalid_tags']: logging.info("Bad tags found: {0}".format(post_tags['invalid_tags']))
                        if any(title_issues): logging.info("Title issues found")
                        message = self.prepare_delete_message(s, formatting_issues, post_tags['invalid_tags'], title_issues)
                        self.moderator.distinguish(s.reply(message))
                        self.moderator.remove(s)
                        obj.deleted = True
                    elif post_tags['valid_tags']:
                        if 'final' in (tag.lower() for tag in post_tags['valid_tags']):
                            # This was the final story, so don't make a post or send a PM
                            logging.info("Final tag found, not sending PM/posting")
                        else:
                            # We have series tags in place. Send a PM
                            logging.info("Series tags found")
                            s.author.message("Reminder about your series post on r/nosleep", SERIES_MESSAGE.safe_substitute(post_url=s.shortlink), None)
                            # Post the remindme bot message
                            self.post_series_reminder(s)
                            obj.sent_series_pm = True

                        # set the series flair for this post
                        try:
                            self.set_submission_flair(s, flair='flair-series')
                        except Exception as e:
                            logging.exception("Unexpected problem setting flair for {0}: {1}".format(s.id, e.message))

                        obj.is_series = True
                    else:
                        # We had no tags at all.
                        logging.info("No tags found in post title.")

                        # Check if this submission has flair
                        if s.link_flair_text == 'Series':
                            obj.is_series = True
                            self.post_series_reminder(s)


                logging.info("Caching metadata for submission {0} for {1} seconds".format(s.id, cache_ttl))
                obj.save()

                # Save for double the TTL in case Reddit's API returns things out
                # of the search date range
                AutoBotSubmission.set_ttl(obj, cache_ttl)
                obj.set_index_ttls(cache_ttl)


    def run(self, forever=False, interval=300):
        """Run the autobot to find posts. Can be specified to run `forever`
        at `interval` seconds per run."""

        bot_start_time = time.time()

        while True:
            try:
                self.process_posts()
            except Exception as e:
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


def transform_and_roll_out():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    sys.excepthook = uncaught_ex_handler

    parser = create_argparser()
    args = parser.parse_args()

    configuration = get_bot_defaults()

    if args.conf:
        with open(args.conf) as cfile:
            configuration.update(parse_config(cfile))

    # Environment variables override configuration file settings
    env_config = get_environment_configuration()
    configuration.update(env_config)

    if ROLLBAR_ACCESS_TOKEN in configuration:
        rollbar.init(configuration[ROLLBAR_ACCESS_TOKEN], configuration[ROLLBAR_ENVIRONMENT])
        rollbar_handler = RollbarHandler()
        rollbar_handler.setLevel(logging.ERROR)
        logging.getLogger('').addHandler(rollbar_handler)


    # This is hack-city, but since we're constructing the redis data
    # after the fact, we'll now bolt the database back into the baseclass
    walrus = Walrus(host=configuration[REDIS_URL], port=configuration[REDIS_PORT], password=configuration[REDIS_PASSWORD])
    AutoBotBaseModel.set_database(walrus)

    bot = AutoBot(configuration)
    bot.run(args.forever, args.interval)


if __name__ == '__main__':
    transform_and_roll_out()
