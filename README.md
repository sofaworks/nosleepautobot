## NoxBot [![CircleCI Production branch build status](https://circleci.com/gh/sofaworks/nosleepautobot/tree/production.svg?style=svg)](https://circleci.com/gh/sofaworks/nosleepautobot/tree/production)

## What is NoxBot?

NoxBot is the bot script currently associated with reddit user /u/NoSleepAutoBot and is used to perform several automatic moderator tasks on /r/NoSleep that are too complex for reddit's own AutoMod.

## What does NoxBot do?

NoxBot performs several moderator tasks automatically that would otherwise be annoying to do manually.

* **NoxBot performs checks for NoSleep's 24-hour rule.**

   Users on NoSleep are only allowed to post once every 24 hours. NoxBot checks each new post's author's history to make sure they haven't posted to the subreddit in the last 24-hours. If they have, NoxBot removes the post and makes a comment on the post informing the author of the rule and telling them the time until they can next post.
* **NoxBot performs checks for NoSleep's title tags rules.**

  NoSleep has strict rules about what sorts of "tags" (things in braces/brackets) can be used in the titles of posts. In short, the only thing allowed in title tags is the part of the story if the story is a series (ex. [Part 1]). NoxBot checks each post for tags and uses a complex regex to determine if the tags are valid or not. If the tags are *not* valid, it removes the post from NoSleep and sends a message (via modmail) to the user telling them what happened and informing them of the rule.
* **NoxBot provides information/rule reminders via PM to authors when they post a new part of a series.**

  If NoxBot detects valid "series" tags in a post title, it will PM the author of the story (via modmail) and remind them that they should double-check the flair on their post, and link back to previous parts of the story. This is not a reprimand in any way -- rather, it is a friendly reminder for series posts.

* **NoxBot flairs things as "series" when it detects a post is a series.**

  If NoxBot detects valid "series" tags in a post title, it will flair the post as a `Series`.

## How does NoxBot run?

NoxBot is scheduled to **run every 3 minutes** (this value can be adjusted). When it runs, it checks the last hour's worth of posts. It also has a caching mechanism in the background that ensures it won't double-count things or do extra work. If the process running NoxBot ever dies, it will automatically restart, so hopefully this will prevent it from being flaky or unresilient.

## Who takes care of NoxBot live and where does it live?

NoxBot was written by reddit user [`/u/SofaAssassin`](https://np.reddit.com/u/SofaAssassin). It is maintained by `/u/SofaAssassin` and [`/u/Himekat`](https://np.reddit.com/u/Himekat) (a NoSleep mod).

NoxBot itself is hosted on and run from **Heroku**, utilizes **Redis** for caching, is continuously deployed via **CircleCI**, and has informational/error logging with **PaperTrail** and **Rollbar**.

## What if I have problems or new feature ideas?

If you have any issues with NoxBot or feature/enhancement requests, it is best to PM either /u/Himekat or /u/SofaAssassin, or make an issue on [NoxBot's Github Issues](https://github.com/sofaworks/nosleepautobot/issues) page.

## How to install and run NoxBot?
_Running NoxBot assumes you already have done the [Reddit OAuth2 quickstart](https://github.com/reddit/reddit/wiki/OAuth2-Quick-Start-Example)_

NoxBot is written in and tested with Python 2.7.x. After you have checked out the source code, you can do the following to start the bot.

    virtualenv venv
    source venv/bin/activate

    pip install -r requirements.txt

    # Copy noxbot.ini.sample to noxbot.ini and modify its values, especially for credentials/authentication.
    python bot.py -c noxbot.ini

### NoxBot execution flags

NoxBot supports a number of flags for running, just type `python bot.py --help` to display a help message with all the supported flags.

	usage: bot.py [-h] [-c CONF] [--forever] [-i INTERVAL]

	optional arguments:
	  -h, --help            show this help message and exit
	  -c CONF, --conf CONF  Configuration file to use for the bot
	  --forever             If specified, runs bot forever.
	  -i INTERVAL, --interval INTERVAL
	                        How many seconds to wait between bot execution cycles.
	                        Only used if "forever" is specified.

### NoxBot Environment Variable-based Configuration

Any configuration setting that can be specified in `noxbot.ini` can alternatively be specified via environment variables, including:

* `AUTOBOT_POST_TIMELIMIT` - Time limit between allowed posts in seconds (**default**: 86400)
* `AUTOBOT_REDIS_URL` - URL to Redis instance (**default**: localhost)
* `AUTOBOT_REDIS_PORT` - Port to connect to on Redis (**default**: 6379)
* `AUTOBOT_REDDIT_USERNAME` - Username the NoxBot authenticates as
* `AUTOBOT_REDDIT_PASSWORD` - Password of specified user
* `AUTOBOT_SUBREDDIT` - Subreddit to run bot against. Specified user **has to be a moderator** of the subreddit.
* `AUTOBOT_CLIENT_ID` - Reddit API OAuth client ID for this application.
* `AUTOBOT_CLIENT_SECRET` - Reddit API OAuth client secret for this application.
* `AUTOBOT_REDIS_BACKEND` - The type of Redis server the bot connects to (**default**: `redis`)


