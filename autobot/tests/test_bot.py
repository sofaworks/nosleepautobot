import os
from unittest import TestCase, mock

from pathlib import Path
from urllib.parse import urlparse, parse_qs

import autobot.bot as bot
from autobot.config import Settings


class TestBotMethods(TestCase):
    def _get_files_dir(self) -> Path:
        return Path(__file__).resolve().parent / "files"

    def test_generate_modmail_link(self):
        modlink = bot.generate_modmail_link('testsr', 'a title', 'some body')
        parsed_url = urlparse(modlink)

        query = parse_qs(parsed_url.query)

        # make sure there are to/subject/message qs components
        self.assertEqual(parsed_url.path, '/message/compose')
        self.assertTrue('to' in query)
        self.assertTrue('message' in query)
        self.assertTrue('subject' in query)
        self.assertEqual(query['message'][0], 'some body')
        self.assertEqual(query['subject'][0], 'a title')

    def test_generate_empty_modmail_link(self):
        modlink = bot.generate_modmail_link('testsr')
        parsed_url = urlparse(modlink)
        query = parse_qs(parsed_url.query)

        self.assertFalse('message' in query)
        self.assertFalse('subject' in query)

    def test_generate_reapproval_message(self):
        msg = bot.generate_reapproval_message('http://localhost/mail')

        self.assertTrue(msg.startswith('[My post](http://localhost/mail)'))

    def test_reject_nsfw_in_title(self):
        '''Test that the presence of 'nsfw' in titles is a rejection'''
        self.assertTrue(bot.title_contains_nsfw('blah blah nsfw blah'))
        self.assertFalse(bot.title_contains_nsfw('NsFw_title_with_spaces'))
        self.assertTrue(bot.title_contains_nsfw('nsfw leading title'))
        self.assertTrue(bot.title_contains_nsfw('Title ending with NSFW'))
        self.assertFalse(bot.title_contains_nsfw('Title without bad words'))
        self.assertTrue(bot.title_contains_nsfw('Title with an [NSFW] tag'))
        self.assertTrue(bot.title_contains_nsfw('!NSFW!'))
        self.assertTrue(bot.title_contains_nsfw('Is this post NSFW?'))
        self.assertTrue(bot.title_contains_nsfw('Hi [Part 2] [NSFW]'))

    def test_reject_long_paragraphs(self):
        '''This test asserts that paragraphs > (length) words are rejected.'''

        # Basic test with just words
        text = ' '.join(['text'] * 351)
        self.assertTrue(bot.paragraphs_too_long([text]))

        # More advanced with punctuations and such.
        # In a naive implementation, word counting
        # could be affected by just splitting on spaces
        # and then things like standalone & would be counted.
        # i.e. len(text.split())
        add_text = ' '.join(['text'] * 349)
        add_text += '& -- text'
        self.assertFalse(bot.paragraphs_too_long([add_text]))

    def test_live_story_paragraphs(self):
        # Soul Cancer initiated issue #13
        files_dir = self._get_files_dir()
        with open(files_dir / "soul_cancer.md", "r") as sc:
            story = sc.read()
            issues = bot.collect_formatting_issues(story)
            self.assertFalse(issues.long_paragraphs)

    def test_chezecaek_full_story(self):
        # Chezecaek initiated issue #17
        files_dir = self._get_files_dir()
        with open(files_dir / "chezecaek.md", "r") as sc:
            story = sc.read()
            issues = bot.collect_formatting_issues(story)
            self.assertFalse(issues.has_codeblocks)

    def test_reject_long_paragraphs_funky_newlines(self):
        '''Test edge case long paragraphs (newlines)'''

        # This test sees if paragraphs that have crappy line breaks
        # are accepted correctly.
        text = ' '.join(['text'] * 300)
        text += '\n \n'
        text += ' '.join(['more'] * 100)
        issues = bot.collect_formatting_issues(text)
        self.assertFalse(issues.long_paragraphs)

    def test_contains_codeblocks(self):
        '''Test for codeblocks in a message'''

        text = '    This starts with four spaces'
        self.assertTrue(bot.contains_codeblocks([text]))

        tab_text = '\tThis starts with a tab'
        self.assertTrue(bot.contains_codeblocks([tab_text]))

        varied_spaces = '   \tThis has three spaces and a tab'
        self.assertTrue(bot.contains_codeblocks([varied_spaces]))

        blank_line_with_spaces = ''.join([' '] * 8)
        self.assertFalse(bot.contains_codeblocks([blank_line_with_spaces]))

        self.assertFalse(bot.contains_codeblocks(['']))

    def test_categorize_tags(self):
        title = 'This is a sample post (volume 1) {part 2} |part 3|'
        tags = bot.categorize_tags(title)
        self.assertEqual(len(tags['invalid_tags']), 0)
        self.assertEqual(len(tags['valid_tags']), 3)
        self.assertEqual(tags['valid_tags'][0], "volume 1")
        self.assertEqual(tags['valid_tags'][1], "part 2")
        self.assertEqual(tags['valid_tags'][2], "part 3")

    def test_update_tags(self):
        '''Test that tags like 'Update #3' and 'Update 99' are allowed'''
        title = 'This is a sample [update #3] [update 100] [update1]'
        tags = bot.categorize_tags(title)
        self.assertEqual(len(tags['invalid_tags']), 1)
        self.assertEqual(len(tags['valid_tags']), 2)
        self.assertEqual(tags['valid_tags'][0], 'update #3')
        self.assertEqual(tags['valid_tags'][1], 'update 100')
        self.assertEqual(tags['invalid_tags'][0], 'update1')

    def test_additional_categorize_tags(self):
        title = 'Truckers Have Some of The Best Stories Threads (update)'
        tags = bot.categorize_tags(title)
        self.assertEqual(len(tags['invalid_tags']), 0)

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

        time_string = bot.englishify_time(int(td.total_seconds()))

        self.assertEqual(time_string, "27 hours, 30 minutes, 30 seconds")

    def test_config(self):
        """Test that standard config loading is correct."""
        timeout = 86400
        cfg = {
            "autobot_post_timelimit": str(timeout),
            "autobot_user_agent": "a-user-agent",
            "autobot_enforce_timelimit": "true",
            "autobot_reddit_username": "username",
            "autobot_reddit_password": "password",
            "autobot_subreddit": "nosleep",
            "autobot_client_id": "client-id",
            "autobot_client_secret": "client-secret",
            "redis_url": "redis://localhost:6379"
        }
        with mock.patch.dict(os.environ, cfg, clear=True):
            s = Settings(_env_file=None)
            self.assertEqual(s.post_timelimit, timeout)
            self.assertIsNone(s.rollbar_token)
        # set our standard arguments

    def test_redis_config_override(self):
        """Test that we can use rediscloud_url or redis_url with priority."""
        cloud_url = "redis://user:pass@127.0.0.1:7000/1"
        local_url = "redis://user:pass@localhost:6379/1"
        cfg = {
            "autobot_post_timelimit": "1",
            "autobot_user_agent": "a-user-agent",
            "autobot_enforce_timelimit": "true",
            "autobot_reddit_username": "username",
            "autobot_reddit_password": "password",
            "autobot_subreddit": "nosleep",
            "autobot_client_id": "client-id",
            "autobot_client_secret": "client-secret",
            "redis_url": local_url
        }
        with mock.patch.dict(os.environ, cfg, clear=True):
            s = Settings(_env_file=None)
            self.assertEqual(s.redis_url, local_url)
            del os.environ["redis_url"]

            # NB Python 3.x dict is ordered
            os.environ["rediscloud_url"] = cloud_url
            os.environ["redis_url"] = local_url
            t = Settings(_env_file=None)
            self.assertEqual(t.redis_url, cloud_url)
