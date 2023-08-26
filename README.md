## nosleepautobot

## Deploy Status

| Environment | Status |
|-------------|--------|
| `staging`   | [![fly.io Staging](https://github.com/sofaworks/nosleepautobot/actions/workflows/deploy.staging.yml/badge.svg?branch=master)](https://github.com/sofaworks/nosleepautobot/actions/workflows/deploy.staging.yml) |
| `prod`   | [![fly.io Staging](https://github.com/sofaworks/nosleepautobot/actions/workflows/deploy.prod.yml/badge.svg?branch=flymetothemoon)](https://github.com/sofaworks/nosleepautobot/actions/workflows/deploy.prod.yml) |

## Build Status

| Branch | Status |
|--------|--------|
| `master` |[![Build / Test](https://github.com/sofaworks/nosleepautobot/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/sofaworks/nosleepautobot/actions/workflows/ci.yml) | 

## What is nosleepautobot?

nosleepautobot is the bot script currently associated with reddit user /u/NoSleepAutoBot and is used to perform several automatic moderator tasks on /r/NoSleep that are too complex for reddit's own AutoMod.

## What does nosleepautobot do?

nosleepautobot performs several moderator tasks automatically that would otherwise be annoying to do manually.

* **nosleepautobot performs checks for NoSleep's 24-hour rule.**

   Users on NoSleep are only allowed to post once every 24 hours. nosleepautobot checks each new post's author's history to make sure they haven't posted to the subreddit in the last 24-hours. If they have, nosleepautobot removes the post and makes a comment on the post informing the author of the rule and telling them the time until they can next post.
* **nosleepautobot performs checks for NoSleep's title tags rules.**

  NoSleep has strict rules about what sorts of "tags" (things in braces/brackets) can be used in the titles of posts. In short, the only thing allowed in title tags is the part of the story if the story is a series (ex. [Part 1]). nosleepautobot checks each post for tags and uses a complex regex to determine if the tags are valid or not. If the tags are *not* valid, it removes the post from NoSleep and makes a comment on the post telling the user what happened and informing them of the rule.

* **nosleepautobot checks for long paragraphs in posts**

  User submissions that contain paragraphs considered 'exceedingly long' (in this case, meaning the submission has a paragraph containing over 350 words) are flagged and temporarily removed. A private message is sent to the author alerting them to update their formatting and submit their post for reapproval.

* **nosleepautobot checks for code blocks in posts**

  Generally, code blocks do not belong in NoSleep submissions. They are typically the byproduct of users writing their stories in another software such as Microsoft Word and using `Tab` characters, which translate to `<pre>` and `<code>` blocks in Markdown. This results in unreadable blocks of text in the resulting submission. nosleepautobot will temporarily remove posts containing such blocks of text and send a private message to the submission author alerting them to fix their formatting and submit their post for reapproval.

* **nosleepautobot provides information/rule reminders via PM to authors when they post a new part of a series.**

  If nosleepautobot detects valid "series" tags in a post title, it will PM the author of the story (via the /r/NoSleepAutoBot user itself) and remind them that they should double-check the flair on their post, and link back to previous parts of the story. This is not a reprimand in any way -- rather, it is a friendly reminder for series posts.

* **nosleepautobot flairs things as "series" when it detects a post is a series.**

  If nosleepautobot detects valid "series" tags in a post title, it will flair the post as a `Series`.

* **nosleep autobot generates moderator activity reports**

## Who takes care of nosleepautobot live and where does it live?

nosleepautobot was originally written by reddit user [`/u/SofaAssassin`](https://np.reddit.com/u/SofaAssassin). It is maintained by `/u/SofaAssassin` and [`/u/Himekat`](https://np.reddit.com/u/Himekat) (a NoSleep mod).

## nosleepautobot in Production

1. The bot checks for new posts every 30 seconds, using the `/new` API endpoint
2. The bot also uses a look-behind of one hour using the `/search` API endpoint, to identify posts that may have been tagged "Series" after the fact
3. Data for the purposes of enforcing time limits and to prevent double-processing submissions is cached.

The canonical nosleepautobot is hosted on and run from fly.io (off the `flymetothemoon` branch), utilizes Redis for caching, and is continuously deployed using Github Actions.

## What if I have problems or new feature ideas?

If you have any issues with nosleepautobot or feature/enhancement requests, please make an issue on [nosleepautobot's Github Issues](https://github.com/sofaworks/nosleepautobot/issues) page.

If your issue is not getting attention, please tag or assign the issue to [@leikahing](https://github.com/leikahing) as he will likely take care of it.

If you really need critical attention, please PM /u/Himekat or /u/SofaAssassin on Reddit.

## How to install and run nosleepautobot?
_Running nosleepautobot assumes you already have done the [Reddit OAuth2 quickstart](https://github.com/reddit/reddit/wiki/OAuth2-Quick-Start-Example)_

nosleepautobot is written and tested with Python 3.10.x. After you have checked out the source code, you can do the following to start the bot.

```
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

# set your env vars or make an autobot.env file
python run_bot.py
```

### nosleepautobot execution flags

nosleepautobot supports some options for running, just type `python3 run_bot.py --help` to display a help message with all the current options.

	usage: run_bot.py [-h] [-c CONF] [--forever] [-i INTERVAL]

	optional arguments:
	  -h, --help            show this help message and exit
	  --forever             If specified, runs bot forever.
	  -i INTERVAL, --interval INTERVAL
	                        How many seconds to wait between bot execution cycles.
	                        Only used if "forever" is specified.

### nosleepautobot Environment Variable-based Configuration

Depending on how you want to deploy and run the bot, it can be configured one of two ways.

The first method is to configure the variables in `autobot.env` file. An example `autobot.env.sample` is included that you can rename and configure.

Alternatively, the bot supports the following environment variables.

| Setting Name | Description | Required? |
| ------------ | ----------- | --------- |
| `DEVELOPMENT_MODE` | Bot runs in dev mode and doesn't do 'live' things against reddit. | No (**default**: `False`) |
| `AUTOBOT_USER_AGENT` | User agent string for the bot | Yes |
| `AUTOBOT_IGNORE_OLDER_THAN` | Don't process posts older than this many seconds | No (**default**: `43200`) |
| `AUTOBOT_IGNORE_OLD_POSTS` | Turn on old post filtering | No (**default**: `True`) |
| `AUTOBOT_POST_TIMELIMIT` | Time limit between allowed posts in seconds | No (**default**: `86400`) |
| `AUTOBOT_ENFORCE_TIMELIMIT` | Reject posts by timelimit? | No (**default**: `True`) |
| `AUTOBOT_REDDIT_USERNAME` | Username the bot authenticates as | Yes |
| `AUTOBOT_REDDIT_PASSWORD` | Password of specified user | Yes |
| `AUTOBOT_CLIENT_ID` | Reddit API OAuth client ID for this application | Yes |
| `AUTOBOT_CLIENT_SECRET` | Reddit API OAuth client secret for this application | Yes |
| `AUTOBOT_SUBREDDIT` | Subreddit to run bot against. Specified user **has to be a moderator** of the subreddit. | Yes |
| `REDIS_URL` | Redis URL | Yes |


## Developing nosleepautobot

In case anyone wants to write code for nosleepautobot (or just as a reminder to me).

### Set Up

Python 3.10+ is required for the source code due to the usage of some new syntax (e.g. union types).

Python 3's [`venv`](https://docs.python.org/3/library/venv.html) module is highly recommended.

Set up would look akin to this...

```
git clone git@github.com:sofaworks/nosleepautobot.git
cd nosleepautobot
python3 -m venv .venv
source .venv/bin/activate

# We use a dev version of the requirements.txt which includes
# all production reqs and some dev-specific modules
pip install -r requirements.dev.txt
```

### Running Unit Tests

The bot has a set of unit tests in `autobot/tests` which can be executed with:

```
python3 -m unittest discover autobot/tests
```

Your tests should pass!

```
(venv) nosleepautobot [master] > python3 -m unittest discover autobot/tests
..................
----------------------------------------------------------------------
Ran 18 tests in 0.005s

OK
```
