#!/usr/bin/env python

# This creates a class for reporting moderator activity

from __future__ import print_function

import os
import sys
import time
import logging
import datetime
import argparse
import itertools

import praw

USER_AGENT = 'r/nosleep moderator tools v1.0 (owner: u/SofaAssassin)'

USAGE_REPLY = '''

----

Did you forgot how to use me? Here are things I can do for you.

## Get Moderator Activity

Send a message entitled "Moderator Activity" to me with one of the following
lines as the first line of the message.

* `activity all` - Get a report of all moderator activities for the current month.
* `activity USERNAME` - Get a report for user or list of users. Separate multiple users by spaces or commas.
'''

def _parser():
    parser = argparse.ArgumentParser(description='Run activity reports for users')
    subparsers = parser.add_subparsers(help='Sub-actions')
    weekly_reporter = subparsers.add_parser('weekly-report', help='Generate weekly action reports for mods')
    weekly_reporter.set_defaults(func=run_weekly_report)
    ondemand_reporter = subparsers.add_parser('ondemand', help='Ondemand reporting')
    ondemand_reporter.set_defaults(func=execute_ondemand)
    return parser

def execute_ondemand():
    print("Running ondemand report")
    ActivityTracker().run_ondemand()

def run_weekly_report():
    today = datetime.datetime.utcnow()
    if today.weekday() != 4:
        print("Not running weekly activity tracker because it's not Friday")
        sys.exit(0)
    print("Running weekly moderator report")
    ActivityTracker().run_weekly()

def quantify(iterable, pred):
    return sum(itertools.imap(pred, iterable))

class ActivityTracker(object):
    def __init__(self):
        self.approved_users = [u.lower() for u in os.environ['AUTOBOT_APPROVED_OPS'].strip().split(',')]
        logging.info('ActivityTracker approved users: {}'.format(self.approved_users))
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
            'Moderator Name|Submission Approvals|Submission Removals|Comment Approvals|Comment Removals',
            ':---|:---:|:---:|:---:|:---:|:---:'
        ]

    def _get_user_report(self, user, start_time):
        dlam = lambda a: a.created_utc > start_time

        return '{}|{}|{}|{}|{}'.format(
            user,
            quantify(self.subreddit.mod.log(action='approvelink', mod=user, limit=1000), dlam),
            quantify(self.subreddit.mod.log(action='removelink', mod=user, limit=1000), dlam),
            quantify(self.subreddit.mod.log(action='approvecomment', mod=user, limit=1000), dlam),
            quantify(self.subreddit.mod.log(action='removecomment', mod=user, limit=1000), dlam)
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
            


    def _generate_activity_reply(self, users):
        if not users:
            return "You didn't specify any users to get a monthly activity report for. Please try again.\n\n" + USAGE_REPLY

        today = datetime.datetime.utcnow()
        month_start = datetime.datetime(today.year, today.month, 1)
        start_ts = time.mktime(month_start.timetuple())
        dlam = lambda a: a.created_utc > start_ts

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
                reply_bits.append(self._get_user_report(user, start_ts)) 
            else:
                invalid_users.append(user)

        if invalid_users:
            additional_notes = 'Invalid users were specified: {}'.format(','.join(invalid_users))
        else:
            additional_notes = 'None'

        full_reply = '''# Moderator Activity Report {}

**This report was generated on {}**.

## Activity Chart

{}

## Additional Notes

* Due to Reddit's API limitations, only the last 1000 actions for any category will be reported.

* {}'''.format(today.strftime('%B %Y'), today.strftime('%B %d %Y at %I:%M %p'), '\n'.join(reply_bits), additional_notes)

        return full_reply

    def _process_activity_requests(self, requests):
        for msg in requests:
            # extract the first line, as that will be the request
            fl = msg.body.splitlines()[0].strip().lower()

            # remove all extraneous spaces
            full_cmd = ' '.join(fl.split(',')).split()
            if not full_cmd:
                reply = 'No action was performed because no command was specified.\n\n' + USAGE_REPLY

            cmd, users = full_cmd[0], full_cmd[1:]
            if cmd in ['activity']:
                reply = self._generate_activity_reply(users)
            else:
                reply = 'I received an invalid command `{}` from you. Please try again.\n\n'.format(cmd) + USAGE_REPLY

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
    logging.info("Running ActivityTracker standalone...")
    parser = _parser()
    args = parser.parse_args()
    args.func()
