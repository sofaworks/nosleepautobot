#!/usr/bin/env python

# This creates a class for reporting moderator activity

from __future__ import print_function

from collections import defaultdict
import os
import sys
import json
import time
import logging
import datetime
import argparse
import itertools

import praw
import requests

USER_AGENT = 'r/nosleep moderator tools v1.0 (owner: u/SofaAssassin)'

USAGE_REPLY = '''

----

Did you forgot how to use me? Here are things I can do for you.

## Get Moderator Activity

Send a message entitled "Moderator Activity" to me with one of the following
commands as the first line of the message.

The possible commands are described in detail below.

### Get Moderator Activity

* `activity all` - Get a report of all moderator activities for the current month.
* `activity USERNAME` - Get a report for a moderator or list of moderators. Separate multiple moderators by spaces or commas.

You can also specify `--start` and `--end` with dates in YEAR-MONTH-DAY FORMAT to get moderator activities
within that date range. Some examples are...

* `activity --start 2019-05-10 --end 2019-05-12 all` - Get a report of all moderator activities between May 10 and May 12, 2019.
* `activity --start 2019-05-10 --end 2019-05-12 USER1,USER2,USER3,USER4` - Get a report of specific moderators' actviities between May 10 and May 12, 2019. Separate multiple users by spaces or commas.

### Get Post Activity Report

**Note that due to how Reddit works, you will only have luck doing this for probably the last month.**

* `posts --start YEAR-MONTH-DAY --end YEAR-MONTH-DAY` - Get a post report between the specified days, with total posts and moderator post actions take during that timeframe.

Examples of this command are...

* `posts --start 2019-08-01 --end 2019-08-31` - Get a post report for all days from August 1 - August 30, 2019
* `posts --start 2019-8-10 --end 2019-8-11` - Get a post report for days from August 10 - August 11, 2019
* `posts --start 2019-8-10 --end 2019-8-10`  - Get a post report for August 10, 2019
'''

def total_posts_in_range(subreddit, begin, end):
    """A wrapper around the PushShift API to get total number of posts in a
    particular subreddit for between `begin` and `end`. The dates are
    inclusive.
   
    PushShift will return a JSON doc that looks like this, with data keyed by
    Unix timestamp (in UTC) and the number of submissions on that day.

    The example input would be:
    subreddit="nosleep"
    begin="2019-08-01"
    end="2019-08-02"
    {
        "aggs": {
            "created_utc": [
                {
                    "doc_count": 153,
                    "key": 1564617600
                },
                {
                    "doc_count": 126,
                    "key": 1564704000
                }
            ]
    }

    The output is going to be a dictionary with key based on ordinal mapped
    to post count on that day, like this:

    {
        700000: 100,
        710000: 200
    }
    """

    tf = "%Y-%m-%d"
    d_end = end + datetime.timedelta(days=1)

    params = {
        "size": 0,
        "aggs": "created_utc",
        "frequency": "day",
        "subreddit": subreddit,
        "after": begin.strftime("%Y-%m-%d"),
        "before": d_end.strftime("%Y-%m-%d")
    }
    r = requests.get("https://api.pushshift.io/reddit/submission/search",
                     params=params)

    data = json.loads(r.text)
    counts = {}
    for c in data["aggs"]["created_utc"]:
        o = datetime.datetime.utcfromtimestamp(c["key"]).toordinal()
        counts[o] = c["doc_count"]
    return counts

def _parser():
    parser = argparse.ArgumentParser(description='Run activity reports for users')
    subparsers = parser.add_subparsers(help='Sub-actions')
    weekly_reporter = subparsers.add_parser('weekly-report', help='Generate weekly action reports for mods')
    weekly_reporter.set_defaults(func=run_weekly_report)
    ondemand_reporter = subparsers.add_parser('ondemand', help='Ondemand reporting')
    ondemand_reporter.set_defaults(func=execute_ondemand)
    return parser

def valid_date(d):
    try:
        return datetime.datetime.strptime(d, '%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentError('{} is an invalid date'.format(d))

def parser_raise(message):
    raise Exception(message)

def command_parser():
    '''Generates a parser that will be used for the comamnds that can be sent in PM'''
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(help='Moderator actions', dest='command')
    activity_parser = subparsers.add_parser('activity', help='Generate activity report for moderators')
    activity_parser.add_argument('--start', type=valid_date)
    activity_parser.add_argument('--end', type=valid_date)
    activity_parser.add_argument('users', type=str, nargs='*')

    posts_parser = subparsers.add_parser('posts', help='Generate post report for time range')
    posts_parser.add_argument('--start', type=valid_date, required=True)
    posts_parser.add_argument('--end', type=valid_date, required=True)
    parser.error = parser_raise
    return parser

def execute_ondemand():
    print("Running ondemand report")
    ActionReporter().run_ondemand()

def run_weekly_report():
    today = datetime.datetime.utcnow()
    if today.weekday() != 4:
        print("Not running weekly activity tracker because it's not Friday")
        sys.exit(0)
    print("Running weekly moderator report")
    ActionReporter().run_weekly()

class ActionReporter(object):
    def __init__(self):
        self.approved_users = [u.lower() for u in os.environ['AUTOBOT_APPROVED_OPS'].strip().split(',')]
        logging.info('ActionReporter approved users: {}'.format(self.approved_users))
        self.reddit = praw.Reddit(user_agent=USER_AGENT,
                                  client_id=os.environ['AUTOBOT_CLIENT_ID'],
                                  client_secret=os.environ['AUTOBOT_CLIENT_SECRET'],
                                  username=os.environ['AUTOBOT_REDDIT_USERNAME'],
                                  password=os.environ['AUTOBOT_REDDIT_PASSWORD'])

        self.subreddit = self.reddit.subreddit(os.environ['AUTOBOT_SUBREDDIT'])

    def _check_pms(self):
        '''Check bot's unread PMs - title it cares about:
        * Moderator Activity'''
        ignored_messages = []
        activity_requests = []
        for msg in self.reddit.inbox.unread(limit=None):
            # drop any messages without an author on the floor
            if not msg.author or msg.author.name.lower() not in self.approved_users:
                ignored_messages.append(msg)

            if msg.subject.strip().lower() == 'moderator activity':
                activity_requests.append(msg)
            else:
                ignored_messages.append(msg)

        self.reddit.inbox.mark_read(ignored_messages)
        self._process_activity_requests(activity_requests)

    def _generate_activity_header(self):
        return [
            'Moderator Name|Submission Approvals|Submission Removals|Comment Approvals|Comment Removals|Active Days',
            ':---|:---:|:---:|:---:|:---:|:---:|:---:'
        ]

    def _get_moderator_actions(self, user, action, limit=1000):
        return self.subreddit.mod.log(action=action, mod=user, limit=limit)

    def _get_user_report(self, user, start, end):
        dlam = lambda a: a.created_utc > start and a.created_utc < end

        action_days = set()
        summary = defaultdict(int)
        for action in ('approvelink', 'removelink', 'approvecomment', 'removecomment'):
            seq = self._get_moderator_actions(user, action)
            for o in itertools.ifilter(dlam, seq):
                summary[action] += 1
                action_days.add(datetime.datetime.utcfromtimestamp(o.created_utc).toordinal())

        return '{}|{}|{}|{}|{}|{}'.format(
            user,
            summary['approvelink'],
            summary['removelink'],
            summary['approvecomment'],
            summary['removecomment'],
            len(action_days),
        )

    def _send_weekly_reports(self):
        today = datetime.datetime.utcnow()
        month_start = datetime.datetime(today.year, today.month, 1)
        start_ts = time.mktime(month_start.timetuple())

        for moderator in self.subreddit.moderator():
            if moderator.name.lower() in ['nosleepautobot', 'automoderator']:
                print("Skipping {}".format(moderator))
                continue
            
            table = self._generate_activity_header()
            table.append(self._get_user_report(moderator, start_ts))

            message = '''
Hi there {}! Here are your total mod actions from {} to {}:

{}

Friendly reminder to meet your minimums for the month!

**NOTE** If you have over 1000 actions in any category for the month, don't expect the value above to be correct. Thanks, Reddt.'''.format(
            moderator.name,
            month_start.strftime('%B %d %Y'),
            today.strftime('%B %d %Y'),
            '\n'.join(table))

            moderator.message('r/nosleep moderation minimum activity reminder', message)
            


    def _generate_activity_reply(self, args):
        #self, users, start=None, end=None):
       
        if args.start and not args.end:
            return 'You specified `--start` but not `--end`. You must specify both together if you want to use date ranges.\n\n{}'.format(USAGE_REPLY)
        if args.end and not args.start:
            return 'You specified `--end` but not `--start`. You must specify both together if you want to use date ranges.\n\n{}'.format(USAGE_REPLY)

        # now generate the activity chart
        users = [item for sublist in [u.split(',') for u in args.users] for item in sublist]
        if not users:
            return "You didn't specify any users to get a monthly activity report for. Please try again.\n\n" + USAGE_REPLY

        today = datetime.datetime.utcnow()
        if args.start:
            start_day = args.start
        else:
            start_day = datetime.datetime(today.year, today.month, 1)

        if args.end:
            end_day = args.end
        else:
            end_day = today

        print("Generating activity for {} to {}".format(start_day, end_day))

        start_ts = time.mktime(start_day.timetuple())
        end_ts = time.mktime(end_day.timetuple())
        reply_date_range = "{} to {}".format(start_day.strftime('%Y-%m-%d'), end_day.strftime('%Y-%m-%d'))
        all_moderators = [mod.name.lower() for mod in self.subreddit.moderator()]

        # For now we only care about 'all' if it's the first user specified
        if users[0].lower() == 'all':
            # get all subreddit moderator reports
            report_users = all_moderators
        else:
            report_users = users

        print("Generating reports for {}".format(report_users))

        reply_bits = self._generate_activity_header()

        invalid_users = []
        for user in report_users:
            if user.lower() in ['nosleepautobot', 'automoderator']:
                print("Skipping reporting for {}".format(user))
                continue

            if user.lower() in all_moderators:
                reply_bits.append(self._get_user_report(user, start_ts, end_ts)) 
            else:
                invalid_users.append(user)

        if invalid_users:
            additional_notes = 'Invalid users were specified: {}'.format(','.join(invalid_users))
        else:
            additional_notes = 'Have a good day!'

        full_reply = '''# Moderator Activity Report {}

**This report was generated on {}**.

## Activity Chart

{}

## Additional Notes

* Due to Reddit's API limitations, only the last 1000 actions for any category will be reported.

* {}'''.format(reply_date_range, today.strftime('%B %d %Y at %I:%M %p'), '\n'.join(reply_bits), additional_notes)

        return full_reply

    def _generate_post_reply(self, args):
        response = [
            'Date|Total r/NoSleep Posts|Total Approved|Total Removed',
            ':---|:---:|:---:|:---:'
        ]
        moderators = [mod.name.lower() for mod in self.subreddit.moderator()]
        post_counts = total_posts_in_range(self.subreddit.display_name, args.start, args.end)

        today = datetime.datetime.utcnow()

        start_ordinal = args.start.toordinal()
        end_ordinal = args.end.toordinal()

        approvals = {}
        removals = {}
        for m in moderators:
            for approval in self._get_moderator_actions(m, 'approvelink'):
                ordinal = datetime.datetime.utcfromtimestamp(approval.created_utc).toordinal()
                approvals.setdefault(ordinal, 0)
                approvals[ordinal] += 1
            for removal in self._get_moderator_actions(m, 'removelink'):
                ordinal = datetime.datetime.utcfromtimestamp(removal.created_utc).toordinal()
                removals.setdefault(ordinal, 0)
                removals[ordinal] += 1 

        # now merge the two
        for k, v in sorted(post_counts.iteritems()):
            response.append(
                '{}|{}|{}|{}'.format(
                    datetime.datetime.fromordinal(k).strftime('%Y-%m-%d'),
                    v,
                    approvals[k],
                    removals[k]
                )
            )

        full_reply = '''# NoSleep Post Report

**This report was generated on {}**.

## Post Activity Chart

{}

## Additional Notes

* Due to various limitations, you may have inaccurate counts if your requested
  days were too long ago.'''.format(
          today.strftime('%B %d %Y at %I:%M %p'),
          '\n'.join(response))

        return full_reply
        

    def _process_activity_requests(self, requests):
        for msg in requests:
            # extract the first line, as that will be the request
            raw_command = msg.body.splitlines()[0].strip().lower()

            parser = command_parser()
            # parse the arguments and command
            problem = None
            try:
                args = parser.parse_args(raw_command.split())
            except Exception, exc:
                # The command didn't parse successfully
                problem = str(exc)

            if problem:
                # bail and send reply
                logging.error("Exception encountered: {}".format(str(exc)))
                reply = 'No action was performed because command was invalid: `{}`\n\n{}'.format(raw_command, USAGE_REPLY)
            else:
                if args.command == 'activity':
                    reply = self._generate_activity_reply(args)
                elif args.command == 'posts':
                    reply = self._generate_post_reply(args)

            msg.reply(reply)
            msg.mark_read()

    def run_weekly(self):
        '''Run weekly reports and send them to each moderator'''
        self._send_weekly_reports()

    def run_ondemand(self):
        '''Run this bot's work to:
        * Check new PMs
        * If special PM is received from specific users, do things'''
        self._check_pms()


if __name__ == '__main__':
    logging.info("Running ActionReporter standalone...")
    parser = _parser()
    args = parser.parse_args()
    args.func()
