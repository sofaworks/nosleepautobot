#!/usr/bin/env python

from string import Template
from collections import namedtuple
import ConfigParser
import logging
import datetime
import argparse
import signal
import time
import sys
import re

import praw
from praw.models.reddit.subreddit import SubredditModeration
from walrus.tusks.rlite import WalrusLite

SubmissionMeta = namedtuple('SubmissionMeta', ['author', 'last_submission_time', 'last_submission_id'])


POST_A_DAY_MESSAGE = Template('Hi there! /r/nosleep limits posts to one post per author per day, '
                      'in order to give all submitters here an equal shot at the front page.\n\n'
                      'As such, your post has been removed. Feel free to repost your story '
                      'in **${time_remaining}**.\n\n'
                      'Confused? See the [mod announcement](http://www.reddit.com/r/NoSleepOOC/comments/1m1spe/rule_addition_one_days_spacing_between_nosleep/) '
                      'on the subject for more information. If you believe your post was removed in error, please '
                      '[message the moderators](http://www.reddit.com/message/compose?to=%2Fr%2Fnosleep).'
                      )

DISALLOWED_TAGS_MESSAGE = ('Hi there! Your post has been removed from /r/nosleep '
                            'as we have strict rules about tags in story titles:\n\n'
                            '**Tags (example: [True], [real experience]) are not allowed.** '
                            'The only thing in brackets **[]**, **{}** or parenthesis **()** '
                            'should be a reference to which "part" of your series the post is. '
                            '**Example**: (part 1) or [Pt2].\n\n'
                            'You will need to delete your story and repost with a corrected title.')

SERIES_MESSAGE = Template('Hi there! It looks like you are writing an /r/nosleep series! '
                  'Awesome! Please be sure to double-check that [your post](${post_url}) '
                  'has "series" flair and please remember to include [a link](${post_url}) '
                  'to the previous part at the top of your story.\n\n'
                  "Don't know how to add flair? Visit your story's comment page "
                  'and look underneath the post itself. Click on the **flair** button '
                  'to bring up a list of options. Choose the "series" option and hit "save"!')

def create_argparser():
    parser = argparse.ArgumentParser(prog='bot.py')
    parser.add_argument('-c', '--conf', required=True, type=str)
    return parser


def reject_submission_by_timelimit(submission, time_now, db=None):
    # look up if this user has a post in storage
    if db:
        value = db.hgetall(submission.author.name)
        if not value:
            logging.info("User '{0}' seen for first time apparently. Adding...".format(submission.author.name))
            # add this to the cache
            h = db.Hash(submission.author.name)
            h.update(last_submission_id=submission.id, last_submission_time=int(submission.created_utc))
        else: 
            next_post_time = int(value['last_submission_time']) + 86400
            if (next_post_time > time_now) and (value['last_submission_id'] != submission.id):
                logging.info("Rejecting subission due to time limit")
                return True
    else:
        # TODO do the manual check of the user submission and
        raise NotImplementedError("Use of `reject_submission_by_timelimit` without a database is currently unsupported")

    return False

def categorize_tags(title):
    # Parses tags out of the post title
    # Valid submission tags are things between [], {}, and ()
    # Valid tag values are:
    # - a single number (shorthand for part #)
    # - Pt/Pt./Part + number (integral or textual)
    # - Vol/Vol./Volume  + number (integral or textual)
    # - Update
    # - Final

    tag_cats = { 'valid_tags': [], 'invalid_tags': [] }

    # this regex might be a little too heavy-handed but it does support the valid tag formats
    allowed_tag_values = re.compile("^(?:(?:vol(?:\.|ume)?|p(?:ar)?t|pt\.)?\s?(?:[1-9][0-9]?|one|two|three|five|ten|eleven|twelve|fifteen|(?:(?:four|six|seven|eight|nine)(?:teen)?))|final|update)$")
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


def englishify_time(td):
    hours, remainder = divmod(td.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    return '{0} hours, {1} minutes, {2} seconds'.format(int(hours), int(minutes), int(seconds))

def parse_config(conf):
    '''conf is a file or file-like pointer'''
    config = ConfigParser.SafeConfigParser()
    config.readfp(conf)

    return {
            'reddit_username': config.get('autobot', 'user'),
            'reddit_password': config.get('autobot', 'password'),
            'client_id': config.get('autobot', 'client_id'),
            'client_secret': config.get('autobot', 'client_secret'),
            'seconds_between_posts': config.getint('autobot', 'seconds_between_allowed_posts'),
            'datafile': config.get('autobot', 'datafile'),
            'subreddit': config.get('autobot', 'subreddit')
        }


if __name__ == '__main__':

    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    #logger = logging.getLogger('autobot')
    #logger.setLevel(logging.DEBUG)
    #console = logging.StreamHandler(sys.stdout)

    #formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    #console.setLevel(logging.INFO)
    #console.setFormatter(formatter)
    #logger.addHandler(console)

    parser = create_argparser()
    args = parser.parse_args()

    with open(args.conf) as cfile:
        configuration = parse_config(cfile)

    logging.info("autobot rolling out with settings...")
    logging.info("Subreddit: {0}".format(configuration['subreddit']))
    logging.info("Reddit username: {0}".format(configuration['reddit_username']))
    logging.info("Redis datafile: {0}".format(configuration['datafile']))
    logging.info("Time between allowed top-level posts: {0} seconds".format(configuration['seconds_between_posts']))

    reddit = praw.Reddit(user_agent='r/nosleep Autobot v 1.0 (by /u/SofaAssassin)',
                client_id=configuration['client_id'],
                client_secret=configuration['client_secret'],
                username=configuration['reddit_username'],
                password=configuration['reddit_password'])

    walrus = WalrusLite(configuration['datafile'])
    subreddit = reddit.subreddit(configuration['subreddit'])
    mod = SubredditModeration(subreddit)
    for submission in subreddit.stream.submissions():
        # for each submission, look up if the user information was already cached.
        # If it hasn't been, add it.
        # If it has, determine if user has posted in the last 24 hours.
        # If user has posted in last 24 hours, then delete the post contents and make
        # a distinguished top-level post.
        now = int(time.time())
        logging.info("Reviewing post '{0}' submitted by '{1}' on {2}".format(submission.id, submission.author.name, submission.created_utc))

        if reject_submission_by_timelimit(submission, now, walrus):
            # make a distinguished comment and remove post
            logging.info("Rejecting submission because of time limit")
            valid_date = (submission.created_utc + configuration['seconds_between_posts']) - now
            time_until_can_post = datetime.timedelta(seconds=valid_date)

            # convert timestamp back to 
            fmt_msg = POST_A_DAY_MESSAGE.safe_substitute(time_remaining=englishify_time(time_until_can_post))
            mod.distinguish(submission.reply(fmt_msg))
            mod.remove(submission)
        else:
            post_tags = categorize_tags(submission.title)
            if post_tags['invalid_tags']:
                # We have bad tags! Delete post and send PM.
                logging.info("Bad tags found: {0}".format(post_tags['invalid_tags']))
                submission.author.message("Your post on /r/nosleep has been removed due to invalid tags", DISALLOWED_TAGS_MESSAGE, subreddit)
                mod.remove(submission)
            elif post_tags['valid_tags']:
                # We have series tags in place. Send a PM
                logging.info("Series tags found")
                submission.author.message("Reminder about your series post on r/nosleep", SERIES_MESSAGE.safe_substitute(post_url=submission.shortlink), subreddit)
            else:
                # We had no tags at all.
                logging.info("No tags")
