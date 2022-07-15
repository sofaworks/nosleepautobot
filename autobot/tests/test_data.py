import unittest

import walrus
import fakeredis

from autobot.models import AutoBotBase, AutoBotSubmission


class TestDataMethods(unittest.TestCase):
    def setUp(self):
        # Replace the base class of Walrus to use fakeredis
        walrus.Walrus.__bases__ = (fakeredis.FakeStrictRedis,)
        self.redis_server = fakeredis.FakeServer()
        self.r = walrus.Walrus(server=self.redis_server)
        AutoBotBase.set_database(self.r)

    def tearDown(self):
        AutoBotBase.set_database(None)

    def test_model(self):
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
        obj = AutoBotSubmission(
                submission_id='test',
                author='pikachu',
                submission_time=1000,
                is_series=True,
                sent_series_pm=False,
                deleted=False)
        obj.save()
        to = 4000
        AutoBotSubmission.set_ttl(obj, to)
        self.assertEqual(
            self.r.ttl('autobot|autobotsubmission:id.test'),
            to)

    def test_index_ttl(self):
        obj = AutoBotSubmission(
                submission_id='test',
                author='pikachu',
                submission_time=1000,
                is_series=True,
                sent_series_pm=False,
                deleted=False)
        to = 10000
        obj.save()
        obj.set_index_ttls(to)
        self.assertEqual(
            self.r.ttl('autobot|autobotsubmission:author.absolute.pikachu'),
            to)
