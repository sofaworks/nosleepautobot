import unittest
from urlparse import urlparse, parse_qs

import bot

class TestBotMethods(unittest.TestCase):

    def test_generate_modmail_link(self):
        modlink = bot.generate_modmail_link('testsr', 'some title', 'some body')
        parsed_url = urlparse(modlink)

        query = parse_qs(parsed_url.query)

        # make sure there are to/subject/message qs components
        self.assertEqual(parsed_url.path, '/message/compose')
        self.assertTrue('to' in query)
        self.assertTrue('message' in query)
        self.assertTrue('subject' in query)
        self.assertEqual(query['message'][0], 'some body')
        self.assertEqual(query['subject'][0], 'some title')

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
        self.assertTrue(bot.title_contains_nsfw(u'blah blah nsfw blah'))
        self.assertFalse(bot.title_contains_nsfw(u'NsFw_title_with_spaces'))
        self.assertTrue(bot.title_contains_nsfw(u'nsfw leading title'))
        self.assertTrue(bot.title_contains_nsfw(u'Title ending with NSFW'))
        self.assertFalse(bot.title_contains_nsfw(u'Title that does not contain bad words'))
        self.assertTrue(bot.title_contains_nsfw(u'Title with an [NSFW] tag'))
        self.assertTrue(bot.title_contains_nsfw(u'!NSFW!'))
        self.assertTrue(bot.title_contains_nsfw(u'Is this post NSFW?'))
        self.assertTrue(bot.title_contains_nsfw(u'Hi [Part 2] [NSFW]'))


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
        with open('tests/soul_cancer.md', 'r') as sc:
            story = sc.read()
            issues = bot.collect_formatting_issues(story)
            self.assertFalse(issues.long_paragraphs)


    def test_chezecaek_full_story(self):
        # Chezecaek initiated issue #17
        with open('tests/chezecaek.md', 'r') as sc:
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
        title = 'This is a sample post (volume 1) {part 2}'
        tags = bot.categorize_tags(title)
        self.assertEqual(len(tags['invalid_tags']), 0)
        self.assertEqual(len(tags['valid_tags']), 2)
        self.assertEqual(tags['valid_tags'][0], "volume 1")
        self.assertEqual(tags['valid_tags'][1], "part 2")


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
        title = 'Truckers Have Some of The Best Stories: Gas Shortages and Unraveling Threads (update)'
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

        time_string = bot.englishify_time(td.total_seconds())

        self.assertEqual(time_string, "27 hours, 30 minutes, 30 seconds")

    def test_empty_configuration_environment(self):
        """Tests that get_environment_configuration returns
        empty configurations if there are no environment variables set"""
        import os
        os.environ.clear()
        self.assertFalse(bool(bot.get_environment_configuration()))

