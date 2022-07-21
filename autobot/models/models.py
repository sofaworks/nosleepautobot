from datetime import datetime
from typing import Iterable, Iterator
import json

from pydantic import BaseModel
import redis


class Submission(BaseModel):
    id: str
    author: str
    submitted: datetime
    series: bool = False
    sent_series_pm: bool = False
    deleted: bool = False

    class Config:
        json_encoders = {
            datetime: lambda _: int(_.timestamp())
        }


class SubmissionHandler:
    def __init__(self, rd: redis.Redis) -> None:
        self.rd = rd

    def persist(self, sub: Submission, ttl: int | None = None) -> None:
        self.rd.set(sub.id, sub.json(), ex=ttl)

    def update(self, sub: Submission) -> None:
        """Updates entry and preserves the key TTL."""
        self.rd.set(sub.id, sub.json(), keepttl=True)

    def get(self, sid: str) -> Submission | None:
        if t := self.rd.get(sid):
            return Submission(**json.loads(t))
        return None

    def get_many(self, ids: Iterable[str]) -> Iterator[Submission]:
        return (_ for _ in self.rd.mget(ids) if _)
