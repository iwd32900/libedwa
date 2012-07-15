"""
A database-backed backend for Event-Driven Web Applications.
"""
import datetime, uuid
import sqlalchemy as sa
from zlib import compress, decompress
from libedwa.core import EDWA, Page, Action

__all__ = ['DatabaseEDWA']


meta = sa.MetaData()
sa.Table('libedwa_page', meta,
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('created_utc', sa.DateTime, index=True, nullable=False, default=datetime.datetime.utcnow),
    sa.Column('user_uuid', sa.String(32), nullable=True),
    sa.Column('page_uuid', sa.String(32), nullable=False),
    sa.Column('data', sa.Binary),
    mysql_engine='InnoDB'
    )
sa.Index('libedwa_user_page_idx', meta.tables['libedwa_page'].c.user_uuid, meta.tables['libedwa_page'].c.page_uuid, unique=True)
sa.Table('libedwa_action', meta,
    sa.Column('page_id', sa.Integer, sa.ForeignKey('libedwa_page.id', ondelete='CASCADE'), nullable=False),
    sa.Column('action_uuid', sa.String(32), nullable=False),
    sa.Column('data', sa.Binary),
    sa.PrimaryKeyConstraint('page_id', 'action_uuid'),
    mysql_engine='InnoDB'
    )

class DatabaseEDWA(EDWA):
    def __init__(self, db_url_or_engine, user_uuid, *args, **kwargs):
        """
        `db_url` - a database connection URL in SQLAlchemy format, or the actual Engine object, or a Connection object.
            At least with the on-disk SQLite backend, a URL or Engine is very inefficient, because each new page/action
            is committed separately.  It's *much* faster (~40x) to do everything within one transaction in one Connection.
        `user_uuid` - up to 32 characters identifying the user / session.  Generate with "uuid.uuid4().hex".  Can be None.
        """
        super(DatabaseEDWA, self).__init__("THIS WILL NEVER BE USED", *args, **kwargs)
        del self._secret_key # just to make sure the dummy value is never used
        if user_uuid: assert len(user_uuid) <= 32
        self._user_uuid = user_uuid
        if hasattr(db_url_or_engine, 'execute'): self.engine = db_url_or_engine
        else: self.engine = sa.create_engine(db_url_or_engine)#, echo_pool=True)
        meta.create_all(bind=self.engine)
    def _typecheck_str(self, s):
        return s # don't need bytes here, Unicode is fine
    def _encode_page(self):
        assert self._curr_page is not None
        pageT = meta.tables['libedwa_page']
        data = compress(self._curr_page.encode(), 1)
        page_uuid = uuid.uuid4().hex
        result = self.engine.execute(pageT.insert(), user_uuid=self._user_uuid, page_uuid=page_uuid, data=data)
        self._curr_page_id = result.last_inserted_ids()[0] # used for _encode_action()
        self._curr_page_encoded = page_uuid
    def _decode_page(self):
        assert self._curr_page_encoded is not None
        pageT = meta.tables['libedwa_page']
        select = sa.select([pageT.c.data], sa.and_(pageT.c.user_uuid == self._user_uuid, pageT.c.page_uuid == self._curr_page_encoded))
        data = self.engine.execute(select).scalar()
        self._set_page(Page.decode(decompress(data)))
    def _encode_action(self, action):
        assert self._mode is not EDWA.MODE_ACTION, "Can't create new actions during an action, because page state is not finalized."
        if self._curr_page_encoded is None: self._encode_page() # ensure page has been serialized
        assert self._curr_page_encoded is not None, "Page state must be serialized before creating an action!"
        actionT = meta.tables['libedwa_action']
        data = compress(action.encode(), 1)
        action_uuid = uuid.uuid4().hex
        self.engine.execute(actionT.insert(), page_id=self._curr_page_id, action_uuid=action_uuid, data=data)
        return action_uuid
    def _decode_action(self, action_id):
        assert self._curr_page_encoded is not None, "Page state must be known when decoding an action!"
        pageT = meta.tables['libedwa_page']
        actionT = meta.tables['libedwa_action']
        jn = pageT.join(actionT, pageT.c.id == actionT.c.page_id)
        select = sa.select([actionT.c.data], sa.and_(pageT.c.user_uuid == self._user_uuid, pageT.c.page_uuid == self._curr_page_encoded, actionT.c.action_uuid == action_id))
        data = self.engine.execute(select).scalar()
        return Action.decode(decompress(data))
    def href(self, action_id):
        return "?%s=%s&%s=%s" % (EDWA.PAGE_KEY, self.make_page_data(), EDWA.ACTION_KEY, action_id)
    def hidden_form(self):
        return ""
