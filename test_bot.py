import unittest

import bot

class TestBotMethods(unittest.TestCase):

    def test_categorize_tags(self):
        title = 'This is a sample post (volume 1) {part 2}'
        tags = bot.categorize_tags(title)
        self.assertEqual(len(tags['invalid_tags']), 0)
        self.assertEqual(len(tags['valid_tags']), 2)
        self.assertEqual(tags['valid_tags'][0], "volume 1")
        self.assertEqual(tags['valid_tags'][1], "part 2")

    def test_categorize_tags_varying_case(self):
        title = 'This is a sample post (VoLuME 1) {PT 2}'
        tags = bot.categorize_tags(title)

        self.assertEqual(len(tags['invalid_tags']), 0)
        self.assertEqual(len(tags['valid_tags']), 2)
        self.assertEqual(tags['valid_tags'][0], "volume 1")
        self.assertEqual(tags['valid_tags'][1], "pt 2")

    def test_englishify_time(self):
        import datetime
        td = datetime.timedelta(days=1, hours=3, minutes=30, seconds=30)

        time_string = bot.englishify_time(td.total_seconds())

        self.assertEqual(time_string, "27 hours, 30 minutes, 30 seconds")

    def test_empty_configuration_environment(self):
        """Tests that get_environment_configuration returns
        empty configurations if there are no environment variables set"""
        import os
        os.environ.clear()
        self.assertFalse(bool(bot.get_environment_configuration()))
