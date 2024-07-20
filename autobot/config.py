from typing import Annotated

from pydantic import Field, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    development_mode: Annotated[
        bool,
        Field(validation_alias="development_mode")
    ] = False
    ignore_older_than: int = 43200
    ignore_old_posts: bool = True
    post_timelimit: int = 86400
    enforce_timelimit: bool = True
    reddit_username: str
    reddit_password: str
    client_id: str
    client_secret: str
    subreddit: str
    user_agent: str
    series_flair_name: str = "flair - series"
    redis_url: Annotated[RedisDsn, Field(validation_alias="redis_url")]
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_prefix="autobot_",
        env_file="autobot.env",
        env_file_encoding="utf-8"
    )
