"""
A library for Event-Driven Web Applications (EDWA).
Please see the README file for explanation!
"""
import base64, hashlib, hmac, sys, zlib
import cPickle as pickle

__all__ = ['EDWA', 'TamperingError']

def _dump_func(f):
    """Given a module-level or instance function, convert to a picklable form."""
    if hasattr(f, "im_class"): return ".".join((f.__module__, f.im_class.__name__, f.__name__))
    else: return ".".join((f.__module__, f.__name__))

def _load_func(x):
    """Restore a usable function from the results of _dump_func()."""
    names = x.split(".")
    # Try first 1, 2, ... names as the module name.
    # (Is it possible to import "foo.bar" without also importing "foo"?)
    module = None
    for ii in xrange(len(names)):
        module = sys.modules.get(".".join(names[:ii+1]))
        if module is not None: break
    else: assert False, "Could not find module for '%s'" % x
    # Add on remaining names to the module name.
    # Convert classes into instances of those classes.
    target = module
    for name in names[ii+1:]:
        target = getattr(target, name)
        if isinstance(target, type): target = target() # call zero-arg constructor on classes
    return target

class TamperingError(ValueError):
    pass

class EDWA(object):
    """The main point of interaction for clients.
    Don't try to pickle these objects between requests;
    just save the secret_key and create a new instance next time.
    Generated action IDs (passed in URLs) are typically 100 - 200 characters long.
    """
    PAGE_KEY = "__libedwa__.page_id"
    ACTION_KEY = "__libedwa__.action_id"
    MODE_RENDER = ['render'] # just a unique object instance, use "is"
    MODE_ACTION = ['action'] # just a unique object instance, use "is"
    def __init__(self, secret_key, use_GET=False):
        assert secret_key, "Must provide a non-empty secret key!"
        # Configuration
        self._secret_key = secret_key # protects actions stored in URLs
        self._use_GET = use_GET # use GET (data in URLs) or POST (no data in URLs)?
        self._max_url_length = 1900 # Internet Explorer is limited to URLs of 2048 characters TOTAL.
        # Record keeping
        self._mode = None # None, MODE_RENDER, MODE_ACTION
        self._curr_page = None
        self._curr_page_encoded = None
    @property
    def context(self):
        """The context object for the currently active page view."""
        return self._curr_page.context
    def _set_page(self, page):
        """Set the current page to some newly-created Page object."""
        assert self._mode is not EDWA.MODE_RENDER, "Can't change location during rendering!  Did you mean to call make_*()?"
        assert page is not None
        self._curr_page = page
        self._curr_page_encoded = None
    def _encode_page(self):
        assert self._curr_page is not None
        self._curr_page_encoded = base64.urlsafe_b64encode(zlib.compress(pickle.dumps(self._curr_page, pickle.HIGHEST_PROTOCOL), 1))
    def _decode_page(self):
        """In this implementation, the page data itself is not signed; it's signed in combination with an action.
        So you want to make sure the action has been verified before decoding the page, or it opens you to attacks against pickle."""
        assert self._curr_page_encoded is not None
        self._set_page(pickle.loads(zlib.decompress(base64.urlsafe_b64decode(self._curr_page_encoded))))
    def _encode_action(self, action):
        """Encode the Action directly as a URL.  Must be paired with page data when passed to run()."""
        assert self._mode is not EDWA.MODE_ACTION, "Can't create new actions during an action, because page state is not finalized."
        assert self._curr_page_encoded is not None, "Page state must be serialized before creating an action!"
        data = base64.urlsafe_b64encode(zlib.compress(pickle.dumps(action, pickle.HIGHEST_PROTOCOL), 1))
        auth = hmac.new(self._secret_key, "%s.%s" % (data, self._curr_page_encoded), hashlib.sha1).digest()
        return "%s.%s" % (base64.urlsafe_b64encode(auth), data)
    def _decode_action(self, action_id):
        """Convert the output of _encode_action() back into a real Action object.
        If the action_id is invalid, raises a TamperingError.
        """
        assert self._curr_page_encoded is not None, "Page state must be known when decoding an action!"
        if "." not in action_id: raise TamperingError("Malformed action_id %s" % action_id)
        auth, data = action_id.split(".", 1)
        if base64.urlsafe_b64decode(auth) != hmac.new(self._secret_key, "%s.%s" % (data, self._curr_page_encoded), hashlib.sha1).digest():
            raise TamperingError("Signature does not match for %s" % action_id)
        action = pickle.loads(zlib.decompress(base64.urlsafe_b64decode(data)))
        return action
    def start(self, request, handler, context=None):
        """No Action provided -- just display the given view.  Used e.g. for the start of a new session."""
        self._set_page(Page(handler, context, None))
        self._encode_page() # needs to be present so view can create actions
        try:
            self._mode = EDWA.MODE_RENDER
            return self._curr_page(request, self)
        finally: self._mode = None
    def run(self, request, action_id, page_id):
        """Run the provided action and display the resulting view."""
        action_id, page_id = str(action_id), str(page_id)
        # Data is saved in two pieces, "base64(hmac).base64(action)" and "base64(page)"
        # However, hmac is computed on "base64(action).base64(page)"
        # Typically, many different actions (small) share the same page data (large).
        self._curr_page_encoded = page_id # don't decode yet, signature not verified
        action = self._decode_action(action_id) # this checks the signature
        self._decode_page() # if no exception, now safe to decode page data
        try:
            self._mode = EDWA.MODE_ACTION
            action(request, self)
        finally: self._mode = None
        self._encode_page() # needs to be present so view can create actions
        try:
            self._mode = EDWA.MODE_RENDER
            return self._curr_page(request, self)
        finally: self._mode = None
    def do_goto(self, handler, context=None):
        """Change the current view, discarding the old view."""
        prev_page = self._curr_page
        self._set_page(Page(handler, context, self._curr_page.parent))
        if hasattr(prev_page, "return_handler"):
            # To avoid having to load/dump the handler function, we just copy it over.
            # TODO: refactor this to be less ugly!
            self._curr_page.return_handler = prev_page.return_handler
            self._curr_page.return_context = prev_page.return_context
    def do_call(self, handler, context=None, return_handler=None, return_context=None):
        """Change the current view, pushing the old view further down the stack.
        If return_handler is provided, it will be called with (edwa_obj, return_value, return_context)
        *immediately* when (and if) the new page returns.
        """
        self._set_page(Page(handler, context, self._curr_page, return_handler, return_context))
    def do_return(self, return_value=None):
        """Discard the current view and pop the previous view from the stack.
        If that view specified a return callback, it will be immediately passed "return_value".
        """
        prev_page = self._curr_page
        self._set_page(self._curr_page.parent)
        prev_page.on_return(self, return_value)
    def make_noop(self):
        """make_action() shortcut to re-display the current view with no changes."""
        return self.make_action(_handle_noop)
    def make_goto(self, handler, context=None):
        """make_action() shortcut to change the current view when clicked."""
        return self.make_action(_handle_goto, _dump_func(handler), context)
    def make_call(self, handler, context=None, return_handler=None, return_context=None):
        """make_action() shortcut to change the current view when clicked."""
        if return_handler: return self.make_action(_handle_call, _dump_func(handler), context, _dump_func(return_handler), return_context)
        else: return self.make_action(_handle_call, _dump_func(handler), context)
    def make_return(self, return_value=None):
        """make_action() shortcut to change the current view when clicked."""
        return self.make_action(_handle_return, return_value)
    def make_action(self, func, *args, **kwargs):
        """Make a URL-safe action "token" that will invoke the given function when token is passed to run()."""
        return self._encode_action(Action(func, args, kwargs))
    def make_page_data(self):
        """Return URL-safe page data token that needs to be passed to run() along with the action token."""
        assert self._curr_page_encoded is not None
        return self._curr_page_encoded
    # Shortcuts for href(make_XXX()):
    def href_noop(self): return self.href(self.make_noop())
    def href_goto(self, *args, **kwargs): return self.href(self.make_goto(*args, **kwargs))
    def href_call(self, *args, **kwargs): return self.href(self.make_call(*args, **kwargs))
    def href_return(self, *args, **kwargs): return self.href(self.make_return(*args, **kwargs))
    def href_action(self, *args, **kwargs): return self.href(self.make_action(*args, **kwargs))
    def href(self, action_id):
        """Convenience function to wrap action_id's in JavaScript href to POST the hidden_form().
        Typical use in Django: <a href='{% eval edwa.href(edwa.make_goto(...)) %}'>link text</a>"""
        if self._use_GET and len(action_id)+len(self._curr_page_encoded) <= self._max_url_length:
            return 'libedwa:%s' % action_id # will be expanded to a full URL by JavaScript
        else:
            return 'javascript:libedwa_post_href("%s");' % action_id # will trigger a POST of a hidden form via JavaScript
    def hidden_form(self):
        """Create a hidden FORM and some JavaScript for an HTML page, to enable the href() helper function.
        Should be placed at the very end of the page, just before </BODY>, after all <A> links!
        """
        return r"""<script type='text/javascript'>
// This part is for links submitted via GET:
re = RegExp("\\blibedwa:");
var anchors = document.getElementsByTagName("A");
for(var i = 0; i < anchors.length; i++) {
  var a = anchors[i];
  a.href = a.href.replace(re, "?%(pkey)s=%(pdata)s&%(akey)s=");
}
// This part is for links submitted via POST:
function libedwa_post_href(action_id) {
  document.getElementById('__libedwa__.action_id').value = action_id; document.getElementById('__libedwa__').submit();
}
</script>
<form id='__libedwa__' action='' method='POST' enctype='multipart/form-data'>
<input type='hidden' name='%(pkey)s' value='%(pdata)s'>
<input type='hidden' id='__libedwa__.action_id' name='%(akey)s' value=''>
</form>
""" % {'pkey':self.PAGE_KEY, 'pdata':self.make_page_data(), 'akey':self.ACTION_KEY}

try:
    import keyczar.keyczar
    class KeyczarEDWA(EDWA):
        def __init__(self, path_to_keys, *args, **kwargs):
            """This version provides excellent security (as far as I know) while still storing all data on the client side.
            Both actions and page states are encrypted, so that clients cannot decode their contents.
            However, it is very, very slow compared to the unencrypted version -- generating 100 links takes several seconds.
            Also, the action IDs (passed in URLs) are ~50% larger, typically 200 - 300 characters."""
            super(KeyczarEDWA, self).__init__("THIS WILL NEVER BE USED", *args, **kwargs)
            del self._secret_key # just to make sure the dummy value is never used
            self.path_to_keys = path_to_keys
            self.crypter = keyczar.keyczar.Crypter.Read(self.path_to_keys)
        def _encode_page(self):
            assert self._curr_page is not None
            self._curr_page_encoded = self.crypter.Encrypt(zlib.compress(pickle.dumps(self._curr_page, pickle.HIGHEST_PROTOCOL), 1)) # also HMAC-SHA1 signed and web-safe base64 encoded
        def _decode_page(self):
            assert self._curr_page_encoded is not None
            self._set_page(pickle.loads(zlib.decompress(self.crypter.Decrypt(self._curr_page_encoded))))
        def _encode_action(self, action):
            assert self._mode is not EDWA.MODE_ACTION, "Can't create new actions during an action, because page state is not finalized."
            assert self._curr_page_encoded is not None, "Page state must be serialized before creating an action!"
            # Although the action will be encrypted and signed,
            # we have to prevent attackers mixing-and-matching actions with page states.
            page_hash = hashlib.sha256(self._curr_page_encoded).digest()
            return self.crypter.Encrypt(zlib.compress(pickle.dumps((action, page_hash), pickle.HIGHEST_PROTOCOL), 1))
        def _decode_action(self, action_id):
            assert self._curr_page_encoded is not None, "Page state must be known when decoding an action!"
            action, page_hash = pickle.loads(zlib.decompress(self.crypter.Decrypt(action_id)))
            if page_hash != hashlib.sha256(self._curr_page_encoded).digest():
                raise TamperingError("Action and page data were mixed-and-matched for %s" % action_id)
            return action
    __all__.append('KeyczarEDWA')
except ImportError:
    pass

try:
    import sqlalchemy as sa
    import datetime, uuid

    meta = sa.MetaData()
    sa.Table('libedwa_page', meta,
             sa.Column('id', sa.Integer, primary_key=True),
             sa.Column('created', sa.DateTime, index=True, nullable=False, default=datetime.datetime.now),
             sa.Column('user_uuid', sa.String(32), nullable=True),
             sa.Column('page_uuid', sa.String(32), nullable=False),
             sa.Column('data', sa.Binary),
             )
    sa.Index('libedwa_user_page_idx', meta.tables['libedwa_page'].c.user_uuid, meta.tables['libedwa_page'].c.page_uuid, unique=True)
    sa.Table('libedwa_action', meta,
             sa.Column('page_id', sa.Integer, sa.ForeignKey('libedwa_page.id'), nullable=False),
             sa.Column('action_uuid', sa.String(32), nullable=False),
             sa.Column('data', sa.Binary),
             sa.PrimaryKeyConstraint('page_id', 'action_uuid')
             )
    
    class DatabaseEDWA(EDWA):
        def __init__(self, db_url_or_engine, user_uuid, *args, **kwargs):
            """
            "db_url" - a database connection URL in SQLAlchemy format, or the actual Engine object.
            "user_uuid" - up to 32 characters identifying the user / session.  Generate with "uuid.uuid4().hex".  Can be None.
            """
            super(DatabaseEDWA, self).__init__("THIS WILL NEVER BE USED", *args, **kwargs)
            del self._secret_key # just to make sure the dummy value is never used
            if user_uuid: assert len(user_uuid) <= 32
            self._user_uuid = user_uuid
            if isinstance(db_url_or_engine, sa.engine.Engine): self.engine = db_url_or_engine
            else: self.engine = sa.create_engine(db_url_or_engine)#, echo_pool=True)
            meta.create_all(bind=self.engine)
        def _encode_page(self):
            assert self._curr_page is not None
            pageT = meta.tables['libedwa_page']
            data = zlib.compress(pickle.dumps(self._curr_page, pickle.HIGHEST_PROTOCOL), 1)
            page_uuid = uuid.uuid4().hex
            result = self.engine.execute(pageT.insert(), user_uuid=self._user_uuid, page_uuid=page_uuid, data=data)
            self._curr_page_id = result.last_inserted_ids()[0] # used for _encode_action()
            self._curr_page_encoded = page_uuid
        def _decode_page(self):
            assert self._curr_page_encoded is not None
            pageT = meta.tables['libedwa_page']
            select = sa.select([pageT.c.data], sa.and_(pageT.c.user_uuid == self._user_uuid, pageT.c.page_uuid == self._curr_page_encoded))
            data = self.engine.execute(select).scalar()
            self._set_page(pickle.loads(zlib.decompress(data)))
        def _encode_action(self, action):
            assert self._mode is not EDWA.MODE_ACTION, "Can't create new actions during an action, because page state is not finalized."
            assert self._curr_page_encoded is not None, "Page state must be serialized before creating an action!"
            actionT = meta.tables['libedwa_action']
            data = zlib.compress(pickle.dumps(action, pickle.HIGHEST_PROTOCOL), 1)
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
            return pickle.loads(zlib.decompress(data))
        def href(self, action_id):
            return "?%s=%s&%s=%s" % (EDWA.PAGE_KEY, self._curr_page_encoded, EDWA.ACTION_KEY, action_id)
        def hidden_form(self):
            return ""
    __all__.append('DatabaseEDWA')
except ImportError:
    pass

def _handle_noop(request, edwa):
    pass
def _handle_goto(request, edwa, handler, context):
    edwa.do_goto(_load_func(handler), context)
def _handle_call(request, edwa, handler, context, return_handler=None, return_context=None):
    if return_handler is not None: return_handler = _load_func(return_handler)
    edwa.do_call(_load_func(handler), context, return_handler, return_context)
def _handle_return(request, edwa, return_value):
    edwa.do_return(return_value)

class Context(dict):
    """A standard dictionary, but one that can be hashed for intern()'ing purposes.
    The hash function is expensive, but I see no other way to avoid choking on nested dictionaries.
    Also features a simple extension which allows dotted access in addition to normal lookup.
    """
    def __hash__(self):
        return hash(pickle.dumps(self))
    def __getattr__(self, name):
        '''Only called when normal lookup fails...'''
        try: return self[name]
        except KeyError: raise AttributeError("No such attribute %s" % name)
    def __setattr__(self, name, value):
        if name in self.__dict__: self.__dict__[name] = value
        else: self[name] = value
    def __delattr__(self, name):
        if name in self.__dict__: del self.__dict__[name]
        else: del self[name]

class Page(object):
    """Wrapper for a view function and its context.
    Pages (and context!) must be immutable once exposed to the web client, or the meaning of URLs could change."""
    def __init__(self, handler, context=None, parent=None, return_handler=None, return_context=None):
        self.handler = _dump_func(handler)
        # In this version, context is NOT inherited from parents:
        if context is None: self.context = Context()
        else:
            if not isinstance(context, Context): context = Context(context)
            self.context = context
        ## In this version, context IS inherited from parents:
        #if parent is not None: self.context = copy.deepcopy(parent.context)
        #else: self.context = Context()
        #if context is not None: self.context.update(context)
        self.parent = parent
        # Return handler will be called by EDWA immediately
        # after calling do_return() when this is the current page.
        if return_handler is not None:
            self.return_handler = _dump_func(return_handler)
            self.return_context = return_context
    def __call__(self, request, edwa):
        handler = _load_func(self.handler)
        return handler(request, edwa)
    def on_return(self, edwa, return_value):
        # edwa.context will be the context of the returned-to page (self.parent.context), not self.context
        if hasattr(self, "return_handler"):
            handler = _load_func(self.return_handler)
            handler(edwa, return_value, self.return_context)
    def __cmp__(self, other):
        return cmp(self.__dict__, other.__dict__)

class Action(object):
    """Wrapper for an action function and its initial state."""
    def __init__(self, handler, args=None, kwargs=None):
        self.handler = _dump_func(handler)
        # By not setting these as empty objects, we can save a little memory when pickled?
        if args: self.args = args
        if kwargs: self.kwargs = kwargs
    def __call__(self, request, edwa):
        handler = _load_func(self.handler)
        args = getattr(self, "args", [])
        kwargs = getattr(self, "kwargs", {})
        return handler(request, edwa, *args, **kwargs)

class ExerciseApi(object):
    """Simple demonstration of the API, without real HTTP requests."""
    def run3(self):
        self.run(DatabaseEDWA, "sqlite:////home/ian.davis/tmp-edwa.db", None)
    def run2(self):
        self.run(KeyczarEDWA, "/home/ian.davis/tmp-pycrypto/crypt_keys")
    def run1(self):
        self.run(EDWA, 'my-secret-key')
    def run(self, EdwaClass, *args):
        def show(action_id):
            print "    Action ID length:", len(action_id) #, action_id
            return action_id
        edwa = EdwaClass(*args)
        edwa.start("<FAKE_REQUEST>", self.page1)
        edwa.run("<FAKE_REQUEST>", show(edwa.make_noop()), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action3)), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_call(self.page2, return_handler=self.onreturn1)), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action1)), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_goto(self.page3)), edwa.make_page_data())
        for i in xrange(100): edwa.make_goto(self.page4)
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action1)), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action2)), edwa.make_page_data()) # this does a call()
        edwa.run("<FAKE_REQUEST>", show(edwa.make_return()), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_return("HIMOM!")), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action1)), edwa.make_page_data())
        print "Suspending..."
        action_id = edwa.make_noop() # save current state
        page_data = edwa.make_page_data()
        print "Re-animating..."
        edwa = EdwaClass(*args) # clean object
        edwa.run("<FAKE_REQUEST>", action_id, page_data) # restore state (current view, etc)
        ## This makes encoding expensive (~ 1 sec), b/c it adds 100 large Action objects to be interned.
        for i in xrange(100): edwa.make_goto(self.page4)
        return edwa
    def page1(self, request, edwa):
        print "On page 1.  Request=%s.  Context=%s." % (request, edwa.context.keys())
    def page2(self, request, edwa):
        print "On page 2.  Request=%s.  Context=%s." % (request, edwa.context.keys())
    def page3(self, request, edwa):
        print "On page 3.  Request=%s.  Context=%s." % (request, edwa.context.keys())
    def page4(self, request, edwa):
        print "On page 4.  Request=%s.  Context=%s." % (request, edwa.context.keys())
    def action1(self, request, edwa):
        print "  Entering action 1.  Request=%s.  Context=%s." % (request, edwa.context.keys())
        edwa.context['foo'] = 'bar'
        edwa.context['big'] = list(range(10000))
        print "  Exiting action 1.  Request=%s.  Context=%s." % (request, edwa.context.keys())
    def action2(self, request, edwa):
        print "  Entering action 2.  Request=%s.  Context=%s." % (request, edwa.context.keys())
        edwa.do_call(self.page4, {"fizz":"buzz"}, self.onreturn1, "EXTRA-STUFF")
        print "  Exiting action 2.  Request=%s.  Context=%s." % (request, edwa.context.keys())
    def action3(self, request, edwa):
        print "  Entering action 3.  Request=%s.  Context=%s." % (request, edwa.context.keys())
        edwa.context['name'] = 'John Q. Public'
        edwa.context['address'] = '123 Main St, Ste 456'
        edwa.context['city'] = 'Couldabeenanywhere'
        edwa.context['state'] = 'Alaska'
        edwa.context['zip'] = '12345-6789'
        edwa.context['phone_home'] = '555-987-6543'
        print "  Exiting action 3.  Request=%s.  Context=%s." % (request, edwa.context.keys())
    def onreturn1(self, edwa, return_value, return_context):
        print "Return value %s in context %s" % (return_value, return_context)
