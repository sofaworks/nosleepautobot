# Changelog

This is a changelog of important/interesting things that go into production releases.

## 2023-08-20

### Fixed

* Fix series check in the `PostAnalyzer` code

## 2023-08-10

### Changed

* Upgrade Docker image from `python:3.11-slim-bullseye` to `python:slim-bookworm`
* Upgrade `msgpack` from 1.0.4 to 1.0.5
* Upgrade `praw` from 7.6.1 to 7.7.1
* Upgrade `pydantic` from 1.10.5 to 1.10.11
* Upgrade `requests` from 2.28.2 to 2.31.0
* Upgrade `redis` from 4.5.1 to 4.5.5
* Upgrade `structlog` from 22.3.0 to 23.1.0

### Fixed

* Fix series flair code to support new subreddit flair names

## 2023-02-24

### Changed

* Upgrade Docker image from `python:3.10-slim-bullseye` to `python:3.11-slim-bullseye`
* Upgrade `mako` from 1.2.2 to 1.2.4
* Upgrade `praw` from 7.6.0 to 7.6.1
* Upgrade `pydantic` from 1.9.1 to 1.10.5
* Upgrade `requests` from 2.28.1 to 2.28.2
* Upgrade `redis` from 4.3.4 to 4.5.1
* Upgrade `structlog` from 22.1.0 to 22.3.0
* Upgrade `python-dotenv` from 0.20.0 to 1.0.0 (automatic via Github Dependabot)
* Add more retries and longer process uptime health check for `supervisor`

### Fixed

* Properly handle rate limit messages that contain singular time units (e.g. `minute` instead of `minutes`)

## 2022-09-20

### Changed

* Use `vector` for shipping logs

## 2022-09-19

### Changed

* Upgrade `mako` from 1.2.1 to 1.2.2 (automatic via Github Dependabot)

### Fixed

* [Issue 123](https://github.com/sofaworks/nosleepautobot/issues/123) - Cache correct post ID for activity checking, fixed timelimit enforcement

## 2022-09-16

## Fixed

* Correctly compare dates for weekly report

## 2022-09-15

### Fixed

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
