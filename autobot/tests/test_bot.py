import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from unittest import TestCase, mock
from urllib.parse import urlparse, parse_qs

from autobot.autobot import englishify_time, PostAnalyzer
from autobot.config import Settings
from autobot.util.reddit_util import SubredditTool


@dataclass
class FakeSubmission:
    title: str = "A reddit title"
    selftext: str = "A reddit text"
    link_flair_text: str = ""


class TestBotMethods(TestCase):
    def _get_files_dir(self) -> Path:
        return Path(__file__).resolve().parent / "files"

    def test_reject_nsfw_in_title(self):
        """Test that the presence of "nsfw" in titles is a rejection"""
        analyzer = PostAnalyzer("series")
        self.assertTrue(analyzer.contains_nsfw_title("blah blah nsfw blah"))
        self.assertFalse(analyzer.contains_nsfw_title("NsFw_title_in_bars"))
        self.assertTrue(analyzer.contains_nsfw_title("nsfw leading title"))
        self.assertTrue(analyzer.contains_nsfw_title("Title ending with NSFW"))
        self.assertFalse(analyzer.contains_nsfw_title("No bad words"))
        self.assertTrue(analyzer.contains_nsfw_title("Has an [NSFW] tag"))
        self.assertTrue(analyzer.contains_nsfw_title("!NSFW!"))
        self.assertTrue(analyzer.contains_nsfw_title("Is this post NSFW?"))
        self.assertTrue(analyzer.contains_nsfw_title("Hi [Part 2] [NSFW]"))

    def test_reject_long_paragraphs(self):
        """This test asserts that paragraphs > (length) words are rejected."""
        analyzer = PostAnalyzer("series")
        # Basic test with just words
        text = " ".join(["text"] * 351)
        self.assertTrue(analyzer.contains_long_paragraphs([text]))

        # More advanced with punctuations and such.
        # In a naive implementation, word counting
        # could be affected by just splitting on spaces
        # and then things like standalone & would be counted.
        # i.e. len(text.split())
        add_text = " ".join(["text"] * 349)
        add_text += "& -- text"
        self.assertFalse(analyzer.contains_long_paragraphs([add_text]))

    def test_live_story_paragraphs(self):
        # Soul Cancer initiated issue #13
        files_dir = self._get_files_dir()
        analyzer = PostAnalyzer("series")
        with open(files_dir / "soul_cancer.md", "r") as sc:
            story = sc.read()
            submission = FakeSubmission(selftext=story)
            meta = analyzer.analyze(submission)
            self.assertFalse(meta.has_long_paragraphs)

    def test_chezecaek_full_story(self):
        # Chezecaek initiated issue #17
        files_dir = self._get_files_dir()
        analyzer = PostAnalyzer("series")
        with open(files_dir / "chezecaek.md", "r") as sc:
            story = sc.read()
            submission = FakeSubmission(selftext=story)
            meta = analyzer.analyze(submission)
            self.assertFalse(meta.has_codeblocks)

    def test_reject_long_paragraphs_funky_newlines(self):
        """Test edge case long paragraphs (newlines)"""

        # This test sees if paragraphs that have crappy line breaks
        # are accepted correctly.
        analyzer = PostAnalyzer("series")
        text = " ".join(["text"] * 300)
        text += "\n \n"
        text += " ".join(['more'] * 100)
        meta = analyzer.analyze(FakeSubmission(selftext=text))
        self.assertFalse(meta.is_invalid())

    def test_contains_codeblocks(self):
        """Test for codeblocks in a message"""

        code_opening = " " * 4
        analyzer = PostAnalyzer("series")
        text = f"{code_opening}This starts with four spaces"
        self.assertTrue(analyzer.contains_codeblocks([text]))

        tab_text = "\tThis starts with a tab"
        self.assertTrue(analyzer.contains_codeblocks([tab_text]))

        varied_spaces = "   \tThis has three spaces and a tab"
        self.assertTrue(analyzer.contains_codeblocks([varied_spaces]))
        self.assertFalse(analyzer.contains_codeblocks([" " * 8]))

        self.assertFalse(analyzer.contains_codeblocks([""]))

    def test_categorize_tags(self):
        title = "This is a sample post (volume 1) {part 2} |part 3|"
        analyzer = PostAnalyzer("series")
        series, final, invalid = analyzer.categorize_tags(title)
        self.assertEqual(len(invalid), 0, f"Unexpected bad tags: {invalid}")
        self.assertTrue(series)
        self.assertFalse(final)

    def test_mixed_series_final(self):
        """Test that you can have a 'final' and other series tags"""
        title = "This is a story [pt. 999][final]"
        analyzer = PostAnalyzer("series")
        series, final, bad_tags = analyzer.categorize_tags(title)
        self.assertTrue(series, "Should be a series but isn't")
        self.assertTrue(final, "Should be final but isn't")
        self.assertEqual(len(bad_tags), 0)

    def test_series_numbers(self):
        """Test that we support numeric and textual part numbers."""
        title = "Story with numeric and text part numbers [part one][vol. 10]"
        analyzer = PostAnalyzer("series")
        series, final, bad_tags = analyzer.categorize_tags(title)
        self.assertTrue(series, "Should be a series but isn't")
        self.assertFalse(final, "Should be final but isn't")
        self.assertEqual(len(bad_tags), 0, f"Unexpected bad tags: {bad_tags}")

    def test_bad_x_of_y_tag(self):
        """Test that tag formatted like (part 1 of 2) aren't allowed."""
        title = "Story with numeric and text part numbers [part 1 of 2]"
        analyzer = PostAnalyzer("series")
        series, final, bad_tags = analyzer.categorize_tags(title)
        self.assertEqual(len(bad_tags), 1, f"Unexpected bad tags: {bad_tags}")

    def test_bad_tags(self):
        """Test that we support numeric and textual part numbers."""
        title = "Story with numeric and text part numbers [oneteen][vol. 10]"
        analyzer = PostAnalyzer("series")
        series, final, bad_tags = analyzer.categorize_tags(title)
        self.assertTrue(series, "Should be a series but isn't")
        self.assertFalse(final, "Should be final but isn't")
        self.assertEqual(len(bad_tags), 1, f"Unexpected bad tags: {bad_tags}")

    def test_update_tags(self):
        """Test that tags like 'Update #3' and 'Update 99' are allowed"""
        analyzer = PostAnalyzer("Series")
        title = "This is a sample [update #3] [update 100] [update1]"
        series, _, bad_tags = analyzer.categorize_tags(title)
        self.assertEqual(len(bad_tags), 1, f"Unexpected bad tags: {bad_tags}")
        self.assertTrue(series)
        self.assertEqual(bad_tags[0], "[update1]")

    def test_naked_update_series_tags(self):
        """Some tags specifically allow you to not specify a number, or you
        can also have just a number"""
        title = "Truckers Have Some of The Best Stories (update)(100)[ten]"
        analyzer = PostAnalyzer("series")
        series, final, bad_tags = analyzer.categorize_tags(title)
        self.assertTrue(series)
        self.assertFalse(final)
        self.assertEqual(len(bad_tags), 0)

    def test_wacky_spaced_tags(self):
        title = "Story with wacky tag spaces ( Vol 1 ) {   PT 2 }| finale  |"
        analyzer = PostAnalyzer("series")
        series, final, bad_tags = analyzer.categorize_tags(title)

        self.assertEqual(len(bad_tags), 0, f"Unexpected bad tags: {bad_tags}")
        self.assertTrue(series)
        self.assertTrue(final)

    def test_categorize_tags_varying_case(self):
        title = "This is a sample post (VoLuME 1) {PT 2}"
        analyzer = PostAnalyzer("series")
        series, final, bad_tags = analyzer.categorize_tags(title)

        self.assertEqual(len(bad_tags), 0, f"Unexpected bad tags: {bad_tags}")
        self.assertTrue(series)
        self.assertFalse(final)

    def test_englishify_time(self):
        td = datetime.timedelta(days=1, hours=3, minutes=30, seconds=30)

        time_string = englishify_time(td.total_seconds())

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

    @mock.patch("praw.Reddit", autospec=True)
    def test_generate_modmail_link(self, reddit_mock):
        mock_sr = mock.Mock()
        mock_sr.display_name = "nosleep"

        reddit_mock.return_value.subreddit = lambda _: mock_sr
        settings = Settings.model_construct()
        settings.development_mode = True
        settings.user_agent = "hello"
        settings.client_id = "123"
        settings.client_secret = "abc"
        settings.subreddit = "nosleep"
        settings.reddit_username = "user1"
        settings.reddit_password = "password"
        reddit_tool = SubredditTool(settings)

        url = reddit_tool.create_modmail_link("test subject", "save me")
        parsed_url = urlparse(url)
        query = parse_qs(parsed_url.query)
        # make sure there are to/subject/message qs components
        self.assertEqual(parsed_url.path, "/message/compose")
        self.assertTrue("to" in query)
        self.assertTrue("message" in query)
        self.assertTrue("subject" in query)
        self.assertEqual(query["message"][0], "save me")
        self.assertEqual(query["subject"][0], "test subject")

    @mock.patch("praw.Reddit", autospec=True)
    def test_generate_empty_modmail_link(self, reddit_mock):
        mock_sr = mock.Mock()
        mock_sr.display_name = "nosleep"

        reddit_mock.return_value.subreddit = lambda _: mock_sr
        settings = Settings.model_construct()
        settings.development_mode = True
        settings.user_agent = "hello"
        settings.client_id = "123"
        settings.client_secret = "abc"
        settings.subreddit = "nosleep"
        settings.reddit_username = "user1"
        settings.reddit_password = "password"
        reddit_tool = SubredditTool(settings)
        modlink = reddit_tool.create_modmail_link()
        parsed_url = urlparse(modlink)
        query = parse_qs(parsed_url.query)

        self.assertFalse("message" in query)
        self.assertFalse("subject" in query)
