from typing import Annotated, Optional

from pydantic import BaseSettings, Field, RedisDsn


class Settings(BaseSettings):
    post_timelimit: int = 86400
    enforce_timelimit: bool = True
    reddit_username: str
    reddit_password: str
    client_id: str
    client_secret: str
    subreddit: str
    user_agent: str
    redis_url: Annotated[RedisDsn, Field(env=["rediscloud_url", "redis_url"])]
    rollbar_token: Annotated[Optional[str], Field(env="rollbar_token")] = None
    rollbar_env: Annotated[str, Field(env="rollbar_env")] = "staging"

    class Config:
        case_sensitive = False
        env_prefix = "autobot_"
        env_file = "autobot.env"
        env_file_encoding = "utf-8"
