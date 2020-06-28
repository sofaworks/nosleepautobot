# -*- coding: utf-8 -*-
'''Defines the test cases for the data/model portion of the bot code.'''

import unittest

import walrus
import fakeredis

from bot import AutoBotBaseModel, AutoBotSubmission


class TestDataMethods(unittest.TestCase):
    def setUp(self):
        '''Set up base test state, including monkey-patching the
        base class of walrus.Walrus.'''
        # Replace the base class of Walrus to use fakeredis
        walrus.Walrus.__bases__ = (fakeredis.FakeStrictRedis,)
        self.redis_server = fakeredis.FakeServer()
        self.redis = walrus.Walrus(server=self.redis_server)
        AutoBotBaseModel.set_database(self.redis)

    def test_model(self):
        '''Make sure that our use of Walrus models is valid for creation
        and filtering.'''
        obj = AutoBotSubmission(
            submission_id='abc',
            author='alexia',
            submission_time=100000,
            is_series=False,
            sent_series_pm=False,
            deleted=False)
        obj.save()
        data = AutoBotSubmission.get(AutoBotSubmission.submission_id == 'abc')
        self.assertEqual(data.submission_id, 'abc')

    def test_set_ttl(self):
        '''Test that the model object TTL is set correctly.'''
        obj = AutoBotSubmission(
            submission_id='test',
            author='pikachu',
            submission_time=1000,
            is_series=True,
            sent_series_pm=False,
            deleted=False)
        obj.save()
        ttl_seconds = 4000
        AutoBotSubmission.set_ttl(obj, ttl_seconds)
        self.assertEqual(
            self.redis.ttl('autobot|autobotsubmission:id.test'),
            ttl_seconds)

    def test_index_ttl(self):
        '''Test that indices are correctly set on objects.'''
        obj = AutoBotSubmission(
            submission_id='test',
            author='pikachu',
            submission_time=1000,
            is_series=True,
            sent_series_pm=False,
            deleted=False)
        ttl_seconds = 10000
        obj.save()
        obj.set_index_ttls(ttl_seconds)
        self.assertEqual(
            self.redis.ttl(
                'autobot|autobotsubmission:author.absolute.pikachu'),
            ttl_seconds)
