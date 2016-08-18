# nosleep autobot

A submission moderator bot for [`/r/nosleep`](https://www.reddit.com/r/nosleep), aiming to replace the bot `NoSleepAutoMod` as it recently stopped functioning and its source code wasn't available for anyone to rehost.

## Implemented Functionality

This is a rather simple bot that does several things at the moment, mostly unique to `/r/nosleep`'s needs.

1. Enforces a time-limit on how long before any particular user can create a post in a subreddit. This is a configurable value but **defaults to 24 hours**.
2. Validates that only series tags are utilized in post titles.

   Acceptable tags are:

   * (Vol, Vol., Volume) + number
   * (Pt, Pt., Part) + number
   * Final
   * Update
   * Just a number (either in integral form like `1, 2, 12, ...` or word form like `one, two, nineteen, ...`)

3. Messages users who create series posts with information about following-up in future posts that continue the series.

## Running

Right now, `autobot` is mostly in a beta form, but should be good for production usage.

Better methods of running this will be provided, but for the time being, in order to run this, I recommend using `virtualenv`.

    # Inside the source directory...
    virtualenv venv
    source venv/bin/activate

    pip install -r requirements.txt

    # Copy autobot.ini.sample to autobot.ini and modify its values, especially for credentials/authentication.
    python bot.py -c autobot.ini

## Technical Design

`autobot` is written in Python 2.7.

It uses the pre-release version of [`praw4`](https://github.com/praw-dev/praw/tree/praw4/praw) for all Reddit interaction.

`rlite` is used as an in-memory caching-store, backed by a persistent on-disk file. This is currently only used for enforcing the 24-hour time limit.
