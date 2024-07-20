from datetime import datetime
from typing import Generic, Generator, Iterable, Optional, Type, TypeVar
import json

from pydantic import BaseModel, field_serializer
import redis


class Submission(BaseModel):
    """This is the model that represents submissions that we cache."""
    id: str
    author: str
    submitted: datetime
    series: bool = False
    sent_series_pm: bool = False
    deleted: bool = False

    @field_serializer('submitted')
    def serialize_submitted(self, submitted: datetime, _info):
        return int(submitted.timestamp())


class Activity(BaseModel):
    """This class is for caching information about when an author
    last did something (like posting)."""
    author: str
    subreddit: str
    last_post_id: str
    last_post_time: datetime

    @field_serializer('last_post_time')
    def serialize_last_post_time(self, last_post_time: datetime, _info):
        return int(last_post_time.timestamp())


T = TypeVar("T", bound=BaseModel)


class DataStore(Generic[T]):
    """This generic class handles the persistence/caching of relevant data
    bits like metadata about posts, info about when users last submitted..."""

    def __init__(self, rd: redis.Redis, factory: Type[T]) -> None:
        self.rd = rd
        self.tf = factory

    def _key(self, sid: str) -> str:
        return f"{self.tf.__name__.lower()}.{sid.lower()}"

    def persist(
        self,
        key: str,
        data: T,
        ttl: int | None = None
    ) -> None:
        ck = self._key(key)
        self.rd.set(ck, data.json(), ex=ttl)

    def update(self, key: str, data: T) -> None:
        """Updates entry and preserves the key TTL."""
        ck = self._key(key)
        self.rd.set(ck, data.json(), keepttl=True)

    def get(self, sid: str) -> T | None:
        ck = self._key(sid)
        if t := self.rd.get(ck):
            return self.tf(**json.loads(t))
        return None

    def get_many(
        self,
        ids: Iterable[str],
        include_none: bool = True
    ) -> Generator[Optional[T], None, None]:
        cks = (self._key(x) for x in ids)
        for r in self.rd.mget(cks):
            if r:
                yield self.tf(**json.loads(r))
            elif include_none:
                yield r
            else:
                continue
        return
