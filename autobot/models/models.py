from walrus import BooleanField, IntegerField, Model, TextField, Walrus


class AutoBotBase(Model):
    __database__ = None
    __namespace__ = 'autobot'

    @classmethod
    def set_database(cls, db: Walrus) -> None:
        cls.__database__ = db


class AutoBotSubmission(AutoBotBase):
    submission_id = TextField(primary_key=True)
    author = TextField(index=True)
    submission_time = IntegerField()
    is_series = BooleanField()
    sent_series_pm = BooleanField()
    deleted = BooleanField()

    @classmethod
    def set_ttl(cls, submission: 'AutoBotSubmission', ttl: int) -> None:
        submission.to_hash().expire(ttl=ttl)

    def set_index_ttls(self, ttl: int) -> None:
        '''Kind of a hacky way to get index keys to expire since they
        are normally created without any TTL whatsoever.'''
        for mi in self._indexes:
            for index in mi.get_indexes():
                key = index.get_key(index.field_value(self)).key
                self.__database__.expire(key, ttl)
