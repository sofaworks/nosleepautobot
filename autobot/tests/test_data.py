import unittest

import fakeredis

from autobot.models import Submission


class TestDataMethods(unittest.TestCase):
    def setUp(self):
        self.srv = fakeredis.FakeServer()
