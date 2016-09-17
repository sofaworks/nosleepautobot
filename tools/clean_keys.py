#!/usr/bin/env python

import os
import sys
import urlparse
import logging

import rollbar
import redis

if __name__ == '__main__':
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    redis_cloud_url = os.getenv('REDISCLOUD_URL')

    cache_ttl = int(os.getenv('AUTOBOT_POST_TIMELIMIT', 86400)) * 2

    rollbar.init(os.getenv('ROLLBAR_ACCESS_TOKEN'), os.getenv('ROLLBAR_ENVIRONMENT'))

    if redis_cloud_url:
        url = urlparse.urlparse(redis_cloud_url)
        redis_host = url.hostname
        redis_port = url.port
        redis_password = url.password
    else:
        raise Exception("Please specify REDISCLOUD_URL")

    r = redis.StrictRedis(host=redis_host, port=redis_port, password=redis_password)

    patterns = ["autobot|autobotsubmission:submission_id.absolute*",
                "autobot|autobotsubmission:author.absolute*"]

    for p in patterns:
        for k in r.scan_iter(match=p, count=100):
            # we only care if a key didn't have a ttl to begin with
            if r.ttl(k) == -1:
                logging.info("Setting TTL on absolute index: {0}".format(k))
                r.expire(k, cache_ttl)
