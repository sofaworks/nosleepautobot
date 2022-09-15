# Changelog

This is a changelog of important/interesting things that go into production releases.

## 2022-09-15

## Fixed

* [Issue 119](https://github.com/sofaworks/nosleepautobot/issues/119) - Added filtering for older posts from `/new`

## 2022-09-09

### Added

* Add a development mode that is read-only using `DEVELOPMENT_MODE` setting

### Changed

* Migrate from Heroku to [fly.io](https://fly.io) for reference production bot
* Switch to development on Python 3.10
* Begin using Python 3.9/3.10 type hints (e.g., std container hinting and `Union` types)
* Move to Github Actions for deployment
* Move CircleCI build config to using `cimg/python:3.10`
* Upgrade `praw` from `7.5.0` to `7.6.0`
* Upgrade `requests` from `2.27.1` to `2.28.1`
* Upgrade `rollbar` from `0.16.2` to `0.16.3`
* Remove `walrus` and switch to using vanilla `redis-py` client
* Remove `string.Template` functionality in favor of `mako` and template files
* Move all post validation into new `PostValidator` class
* Move Reddit/Subreddit utilities into `SubredditTool` class
* Rewrite moderator activity script as `ReportService` with new `run_report_service.py` script
* Change to using `new()` sublistings for posts
* Split processing into fetching new posts, then processing recent older posts
* Start caching per-user activity information for time limit checks
* Introduce `pydantic` for settings management
* Introduce `structlog` for logging
* Introduce `schedule` for running reports

### Fixed

* [Issue 99](https://github.com/sofaworks/nosleepautobot/issues/99) - Fix search when usernames are hyphenated
* [Issue 102](https://github.com/sofaworks/nosleepautobot/issues/102) - Add filtering for submissions in search results that aren't from the bot's managed subreddit
* [Issue 110](https://github.com/sofaworks/nosleepautobot/issues/110) - Fixed sending series PM for posts tagged `Series` after-the-fact
* [Issue 111](https://github.com/sofaworks/nosleepautobot/issues/111) - Remove double checking for redditor's "most recent posts"
* [Issue 112](https://github.com/sofaworks/nosleepautobot/issues/112) - Change post processing to use `new()` listings
* [Issue 113](https://github.com/sofaworks/nosleepautobot/issues/113) - Migrated off Heroku
