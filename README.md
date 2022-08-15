## NoxBot

## Build Status

| Branch | Status |
|--------|--------|
| `heroku` | [![CircleCI Heroku branch build status](https://circleci.com/gh/sofaworks/nosleepautobot/tree/heroku.svg?style=svg)](https://circleci.com/gh/sofaworks/nosleepautobot/tree/heroku) |
| `master` | [![CircleCI Master branch build status](https://circleci.com/gh/sofaworks/nosleepautobot/tree/master.svg?style=svg)](https://circleci.com/gh/sofaworks/nosleepautobot/tree/master) |

## What is NoxBot?

NoxBot is the bot script currently associated with reddit user /u/NoSleepAutoBot and is used to perform several automatic moderator tasks on /r/NoSleep that are too complex for reddit's own AutoMod.

## What does NoxBot do?

NoxBot performs several moderator tasks automatically that would otherwise be annoying to do manually.

* **NoxBot performs checks for NoSleep's 24-hour rule.**

   Users on NoSleep are only allowed to post once every 24 hours. NoxBot checks each new post's author's history to make sure they haven't posted to the subreddit in the last 24-hours. If they have, NoxBot removes the post and makes a comment on the post informing the author of the rule and telling them the time until they can next post.
* **NoxBot performs checks for NoSleep's title tags rules.**

  NoSleep has strict rules about what sorts of "tags" (things in braces/brackets) can be used in the titles of posts. In short, the only thing allowed in title tags is the part of the story if the story is a series (ex. [Part 1]). NoxBot checks each post for tags and uses a complex regex to determine if the tags are valid or not. If the tags are *not* valid, it removes the post from NoSleep and makes a comment on the post telling the user what happened and informing them of the rule.

* **NoxBot checks for long paragraphs in posts**

  User submissions that contain paragraphs considered 'exceedingly long' (in this case, meaning the submission has a paragraph containing over 350 words) are flagged and temporarily removed. A private message is sent to the author alerting them to update their formatting and submit their post for reapproval.

* **NoxBot checks for code blocks in posts**

  Generally, code blocks do not belong in NoSleep submissions. They are typically the byproduct of users writing their stories in another software such as Microsoft Word and using `Tab` characters, which translate to `<pre>` and `<code>` blocks in Markdown. This results in unreadable blocks of text in the resulting submission. NoxBot will temporarily remove posts containing such blocks of text and send a private message to the submission author alerting them to fix their formatting and submit their post for reapproval.

* **NoxBot provides information/rule reminders via PM to authors when they post a new part of a series.**

  If NoxBot detects valid "series" tags in a post title, it will PM the author of the story (via the /r/NoSleepAutoBot user itself) and remind them that they should double-check the flair on their post, and link back to previous parts of the story. This is not a reprimand in any way -- rather, it is a friendly reminder for series posts.

* **NoxBot flairs things as "series" when it detects a post is a series.**

  If NoxBot detects valid "series" tags in a post title, it will flair the post as a `Series`.

## Who takes care of NoxBot live and where does it live?

NoxBot was written by reddit user [`/u/SofaAssassin`](https://np.reddit.com/u/SofaAssassin). It is maintained by `/u/SofaAssassin` and [`/u/Himekat`](https://np.reddit.com/u/Himekat) (a NoSleep mod).

## NoxBot in Production

NoxBot is scheduled to **run every 2 minutes**. When it runs, it checks the last hour's worth of posts. It also has a caching mechanism in the background that ensures it won't double-count things or do extra work. If the process running NoxBot ever dies, it will automatically restart, so hopefully this will prevent it from being flaky or unresilient.

NoxBot is hosted on and run from **Heroku** (off the `heroku` branch), utilizes **Redis** for caching, is continuously deployed via **CircleCI**, and has informational/error logging with **PaperTrail** and **Rollbar**.

## What if I have problems or new feature ideas?

If you have any issues with NoxBot or feature/enhancement requests, please make an issue on [NoxBot's Github Issues](https://github.com/sofaworks/nosleepautobot/issues) page.

If your issue is not getting attention, please tag or assign the issue to @leikahing as he will likely take care of it.

If you really need critical attention, please PM /u/Himekat or /u/SofaAssassin on Reddit.

## How to install and run NoxBot?
_Running NoxBot assumes you already have done the [Reddit OAuth2 quickstart](https://github.com/reddit/reddit/wiki/OAuth2-Quick-Start-Example)_

NoxBot is written and tested with Python 3.10.x. After you have checked out the source code, you can do the following to start the bot.

```
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# set your env vars or make an autobot.env file
python run_bot.py
```

### NoxBot execution flags

NoxBot supports a number of flags for running, just type `python run_bot.py --help` to display a help message with all the supported flags.

	usage: run_bot.py [-h] [-c CONF] [--forever] [-i INTERVAL]

	optional arguments:
	  -h, --help            show this help message and exit
	  --forever             If specified, runs bot forever.
	  -i INTERVAL, --interval INTERVAL
	                        How many seconds to wait between bot execution cycles.
	                        Only used if "forever" is specified.

### NoxBot Environment Variable-based Configuration

The bot reads the following environment variables for configuration.

| Setting Name | Description | Required? |
| ------------ | ----------- | --------- |
| `DEVELOPMENT_MODE` | Bot runs in dev mode and doesn't do 'live' things against reddit. | No (**default**: `False`) |
| `AUTOBOT_USER_AGENT` | User agent string for the bot | Yes |
| `AUTOBOT_POST_TIMELIMIT` | Time limit between allowed posts in seconds | No (**default**: `86400`) |
| `AUTOBOT_REDDIT_USERNAME` | Username the bot authenticates as | Yes |
| `AUTOBOT_REDDIT_PASSWORD` | Password of specified user | Yes |
| `AUTOBOT_CLIENT_ID` | Reddit API OAuth client ID for this application | Yes |
| `AUTOBOT_CLIENT_SECRET` | Reddit API OAuth client secret for this application | Yes |
| `AUTOBOT_SUBREDDIT` | Subreddit to run bot against. Specified user **has to be a moderator** of the subreddit. | Yes |
| `REDIS_URL` | Redis URL | Yes |

Configuration settings can also be specified via a `autobot.env` file. An example `autobot.env.sample` is included that you can rename and configure.

## Developing NoxBot

In case anyone wants to write code for NoxBot (or just as a reminder to me).

### Set Up

**Python 2.x support has been removed as Python 2.x [has been EOL'ed as of January 1, 2020](https://www.python.org/doc/sunset-python-2/).**

python3's `venv` module is highly recommended.

Set up would look akin to this...

```
git clone git@github.com:sofaworks/nosleepautobot.git
cd nosleepautobot
python -m venv .venv
source .venv/bin/activate

# We use a dev version of the requirements.txt which includes
# all production reqs and some dev-specific modules
pip install -r requirements.dev.txt
```

### Running Unit Tests

The bot has a set of unit tests in `autobot/tests` which can be executed with:

```
python -m unittest discover autobot/tests
```

Your tests should pass!

```
(venv) nosleepautobot [master] > python -m unittest discover autobot/tests
..................
----------------------------------------------------------------------
Ran 18 tests in 0.005s

OK
```
