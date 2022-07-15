# Changelog

This is a changelog of changes that ship to production.

## Unreleased (estimated July 15 2022)

### Changed

* Begin using Python 3.9-level type hints
* Begin using `heroku` branch instead of `production` for deployments
* Move CircleCI build config to using `cimg/python:3.10`
* Upgrade `praw` from `7.5.0` to `7.6.0`
* Upgrade `requests` from `2.27.1` to `2.28.1`
* Upgrade `rollbar` from `0.16.2` to `0.16.3`
* Upgrade `walrus` from `0.9.1` to `0.9.2`

### Fixed

* [Issue 99](https://github.com/sofaworks/nosleepautobot/issues/99) - Fix search when usernames are hyphenated
* [Issue 102](https://github.com/sofaworks/nosleepautobot/issues/102) - Add filtering for submissions in search results that aren't from the bot's managed subreddit
