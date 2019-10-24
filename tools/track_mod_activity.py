#!/usr/bin/env python

from __future__ import print_function

from collections import defaultdict
import os
import sys
import time
import logging
import datetime
import itertools

import praw
from praw.models.reddit.subreddit import SubredditModeration


MOD_ACTIONS = ['approvelink', 'removelink', 'approvecomment', 'removecomment']

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

        action_days = set()
        summary = defaultdict(int)
        for action in MOD_ACTIONS:
            seq = subreddit.mod.log(action=action, mod=moderator, limit=1000)
            for o in itertools.ifilter(dlam, seq):
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
        
        moderator.message("r/nosleep moderation minimum activity reminder", message)
