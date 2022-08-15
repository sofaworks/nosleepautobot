from pathlib import PurePath

from mako.lookup import TemplateLookup


class MessageBuilder:
    TEMPLATES = {
        "repproval": "reapproval.template",
        "series-pm": "series_message.md.template",
        "series-comment": "series_comment.md.template",
        "post-a-day": "post_a_day.md.template",
        "post-deleted": "post_removed.md.template"
    }

    def __init__(self, template_dir: PurePath) -> None:
        self.mako = TemplateLookup([template_dir])

    def _render(self, template: str, **kwargs) -> str:
        t = self.mako.get_template(self.TEMPLATES[template])
        return t.render(**kwargs)

    def create_approval_msg(self, post_url: str) -> str:
        return self._render("repproval", post_url=post_url)

    def create_post_a_day_msg(
        self,
        remaining: str,
        modmail_link: str
    ) -> str:
        return self._render(
            "post-a-day",
            time_remaining=remaining,
            modmail_link=modmail_link
        )

    def create_deleted_post_msg(
        self,
        post_url: str,
        *,
        modmail_link: str,
        reapproval_modmail: str | None = None,
        permanent: bool = False,
        has_nsfw_title: bool = False,
        has_codeblocks: bool = False,
        long_paragraphs: bool = False,
        invalid_tags: str | None = None,
    ) -> str:
        template_args = {k: v for k, v in locals().items() if k != "self"}
        return self._render(
            "post-deleted",
            **template_args
        )

    def create_series_msg(self, post_url: str) -> str:
        """This creates the series PM message that informs the
        poster about how a series is handled by the bot."""
        return self._render("series-pm", post_url=post_url)

    def create_series_comment(self, sub_url: str) -> str:
        return self._render("series-comment", subscribe_url=sub_url)
