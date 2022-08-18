from typing import Annotated

from pydantic import BaseSettings, Field, RedisDsn


class Settings(BaseSettings):
    development_mode: Annotated[bool, Field(env="development_mode")] = False
    post_timelimit: int = 86400
    enforce_timelimit: bool = True
    reddit_username: str
    reddit_password: str
    client_id: str
    client_secret: str
    subreddit: str
    user_agent: str
    series_flair_name: str = "series"
    redis_url: Annotated[RedisDsn, Field(env=["rediscloud_url", "redis_url"])]
    rollbar_token: Annotated[str | None, Field(env="rollbar_token")] = None
    rollbar_env: Annotated[str, Field(env="rollbar_env")] = "staging"

    class Config:
        case_sensitive = False
        env_prefix = "autobot_"
        env_file = "autobot.env"
        env_file_encoding = "utf-8"
