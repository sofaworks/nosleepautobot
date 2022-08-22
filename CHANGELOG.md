# Changelog

This is a changelog of changes that ship to production.

## Unreleased (estimated August 19 2022)

### Added

* Add a development mode that is read-only

### Changed

* Switch to development on Python 3.10
* Begin using Python 3.9-level type hints
* Begin using `heroku` branch instead of `production` for deployments
* Move CircleCI build config to using `cimg/python:3.10`
* Upgrade `praw` from `7.5.0` to `7.6.0`
* Upgrade `requests` from `2.27.1` to `2.28.1`
* Upgrade `rollbar` from `0.16.2` to `0.16.3`
* Remove `walrus` and switch to using vanilla `redis-py` client
* Remove `string.Template` functionality in favor of `mako` and template files
* Move all post validation into new `PostValidator` class
* Move Reddit/Subreddit utilities into `SubredditTool` class
* Introduce `pydantic` for settings management
* Introduce `structlog` for logging

### Fixed

* [Issue 99](https://github.com/sofaworks/nosleepautobot/issues/99) - Fix search when usernames are hyphenated
* [Issue 102](https://github.com/sofaworks/nosleepautobot/issues/102) - Add filtering for submissions in search results that aren't from the bot's managed subreddit
* [Issue 110](https://github.com/sofaworks/nosleepautobot/issues/110 ) - Fixed sending series PM for posts tagged `Series` after-the-fact
