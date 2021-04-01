#!/usr/bin/env python3

from collections import defaultdict
import os
import re
import sys
import logging
import datetime
import time

import praw
from praw.exceptions import RedditAPIException


MOD_ACTIONS = ['approvelink', 'removelink', 'approvecomment', 'removecomment']

_pattern = re.compile(r'(?P<number>[0-9]+) (?P<unit>\w+)s? before trying.*\.$',
                      re.IGNORECASE)


def handle_rate_limit(exc: RedditAPIException) -> None:
    time_map = {
        'seconds': 1,
        'minutes': 60,
        'hours': 60 * 60,
    }
    matches = re.search(_pattern, exc.message)
    if not matches:
        logging.error(f'Unable to parse rate limit message {exc.message!r}')
        return
    logging.info(f"Matched: {matches}")
    delay = int(matches['number']) * time_map[matches['unit']]
    time.sleep(delay + 1)


if __name__ == '__main__':
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    reddit = praw.Reddit(user_agent='/r/nosleep AutoBot v1.0 (by /u/SofaAssassin)',
            client_id=os.environ['AUTOBOT_CLIENT_ID'],
            client_secret=os.environ['AUTOBOT_CLIENT_SECRET'],
            username=os.environ['AUTOBOT_REDDIT_USERNAME'],
            password=os.environ['AUTOBOT_REDDIT_PASSWORD'])

    subreddit = reddit.subreddit(os.environ['AUTOBOT_SUBREDDIT'])

    today = datetime.datetime.utcnow()

    # Run every Friday - since this thing runs in Heroku, which has
    # very inflexible scheduling (best is once-per-day), this will be enforced
    # here
    if today.weekday() != 4:
        print("Not running mod activity tracker because it's not Friday")
        sys.exit(0)

    month_start = datetime.datetime(today.year, today.month, 1)
    start_ts = time.mktime(month_start.timetuple())

    if not subreddit.user_is_moderator:
        raise AssertionError("User is not moderator of subreddit")

    dlam = lambda a: a.created_utc > start_ts
    # Now get list of all moderators in subreddit
    # Iterate through them and build up all their actions
    for moderator in subreddit.moderator():
        # blacklist moderators
        if moderator.name.lower() in ['nosleepautobot', 'automoderator']:
            print("Skipping {}".format(moderator))
            continue
        else:
            print("Generating report for {}".format(moderator))

        action_days = set()
        summary = defaultdict(int)
        for action in MOD_ACTIONS:
            seq = subreddit.mod.log(action=action, mod=moderator, limit=1000)
            for o in filter(dlam, seq):
                summary[action] += 1
                action_days.add(datetime.datetime.utcfromtimestamp(o.created_utc).toordinal())

        message = '''
Hi there {}! Here are your total mod actions from {} to {}:


* **Post Approvals**: {}
* **Post Rejections**: {}
* **Comment Approvals**: {}
* **Comment Rejections**: {}
* **Days Active**: {}

Friendly reminder to meet your minimums for the month!

**NOTE** If you have over 1000 actions in any category for the month, don't expect the value above to be correct. Thanks, Reddit.'''.format(
        moderator.name,
        month_start.strftime('%B %d %Y'),
        today.strftime('%B %d %Y'),
        summary['approvelink'],
        summary['removelink'],
        summary['approvecomment'],
        summary['removecomment'],
        len(action_days))
        print(message)

        print(reddit.auth.limits)
        while True:
            try:
                moderator.message("r/nosleep moderation minimum activity reminder", message)
            except RedditAPIException as e:
                rate_limited = False
                for subex in e.items:
                    if subex.error_type == "RATELIMIT":
                        rate_limited = True
                        logging.warning(
                            "Ratelimit - artificially limited by Reddit. Sleeping for requested time!"
                        )
                        handle_rate_limit(e)
                if rate_limited:
                    continue
                else:
                    raise e
            break
