"""
A library for Event-Driven Web Applications (EDWA).

EDWA is appropriate for applications that are similar to traditional desktop applications, in that
they need to maintain state for a particular user, but are not focused on sharing that state with others.
It is particularly useful when navigation between "pages" or "states" is dynamic and stack-like,
and/or when links are expected to carry out UI "actions".

A typical example might be a web store: from a product page, you click a link to add it to the shopping cart.
(That link does not have the typical "display some information" sematics of a normal HTTP GET,
but rather the "change my internal state" sematics of HTTP POST -- but it's implemented via GET.)
From the shopping cart, you enter a "subroutine" to change your (stored) shipping preferences.
Then you "pop" back up to the shopping cart, and click a link that causes your shipping charges to be recalculated.
Finally, you pop up again to the product page you started from.
EDWA is particularly focused on this kind of call/return and action/response navigation logic.

The current "call stack" is stored directly as a signed, base64-encoded URL where possible.
These links can be bookmarked and even emailed to others (although they may be quite long),
and will always preserve immutably their starting state, even if re-visited many times.
(Although this data is opaque, it could be decoded and inspected by a savvy client.
One could add (symmetric) encryption to prevent this.)
If the associated data grows too large, it is transparently substituted for a unique ID,
and the data itself is stored in the EDWA object.
(That object must then be persisted somehow, such as in the "session" object provided by your web framework.
Since retrieval then depends on the session ID, usually stored in a cookie, these cannot be emailed.)

Unlike my earlier efforts, this framework does not break the browser back button,
nor does it prevent the user from "forking" the application by opening a new tab or window.
However, if page contexts become large, the total size of the EDWA object may grow without bound.
If the total size exceeds a user-defined limit, "old" actions (not generated by the current view)
will be flushed away, which may break the back button and/or "forked" versions of the app.
Unfortunately, that's about the best I can do.

By convention, each "major state" or "page" of the application is represented as a class with a render() function.
Actions associated with that page are additional member functions.
The class is only used as a convenient grouping namespace: it must have a no-argument constructor,
and there is no guarantee that render() and the action function(s) will be called on the same instance.
Thus, if you prefer, all view AND actions may simply be top-level functions in one or more modules.

Views (e.g. render()) take two arguments, the current EDWA object and a "request" object from e.g. the web framework.
The EDWA object contains a "context" dictionary that is analogous to kwargs in a typical Python function.
Views should be "pure" -- they should not modify their context, although this is not enforced.
To protect against accidental misuse of the library, view are prohibited from calling do_goto/call/return().
They can create links to actions, however, using make_action().
Shortcuts are provided for *links* that navigate to other views: make_goto(), make_call(), and make_return().
For a link that simply re-displays the current view, call make_noop().

Actions also take two arguments, the current EDWA object and the web framework "request" object.
Actions may use EDWA.context to add/change/remove context variables for the current view,
or may change the current view using do_goto(), do_call(), or do_return().

Although I've tried to make this as efficient as possible, generating a simple action link takes ~300 us,
or about 20 times longer than just pickling and 5 times longer than pickling and compressing.
Most of this appears to be the HMAC signature, which protects the URLs from tampering.
In situations where server performance is an issue, this library is only appropriate if the back-end
processing of actions is significantly more costly than the overhead generated by EDWA.
(Probably true in most cases.  But your mileage may vary.)
On the other hand, if everything can be encoded as a URL, it may eliminate the need for a round-trip to the database.

TODO:
- Sign (and optionally, encrypt) URLs using Google KeyCzar, to support key rotation, etc.
"""
import base64, copy, hashlib, hmac, sys, zlib
import cPickle as pickle

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
    The web framework should take care of creating one such object per visitor,
    and persisting it between requests.
    """
    def __init__(self, secret_key, size_limit=None):
        """The serialized size of this object may still exceed size_limit if
        the current view generated many large actions."""
        assert secret_key, "Must provide a non-empty secret key!"
        # Configuration
        self._max_url_length = 2000 # http://stackoverflow.com/questions/417142/what-is-the-maximum-length-of-an-url
        self._secret_key = secret_key # protects actions stored in URLs
        self._size_limit = size_limit
        # Record keeping
        self._all_actions = {} # actually, only ones too big to fit in URLs
        self._curr_page = None
        self._next_id = 1
        self._new_actions = [] # big actions added in this pass
        self._all_contexts = {} # contexts of pages of big actionss
        self._rendering = False
    def _set_page(self, page, clone):
        """Set the current page to some newly-created Page object."""
        assert page is not None
        assert not self._rendering, "Can't change location during rendering!  Did you mean to call make_*()?"
        # Cloning is wasteful if the handler does not modify the current context,
        # either because it changes location first or because no change is needed.
        # We try to fix that later by intern()'ing the context objects.
        if clone and page: page = page.clone()
        self._curr_page = page
    def _new_id(self):
        """Generate a new unique ID token for a stored Action.
        If you override this (e.g. to use a GUID) make sure whatever you return
        is a URL-safe string with no dots (".") in it."""
        new_id = self._next_id
        self._next_id += 1
        return str(new_id)
    def _encode_action(self, action):
        """If possible, encode the Action directly as a URL.  If not, store it internally and return an ID token."""
        data = zlib.compress(pickle.dumps(action, pickle.HIGHEST_PROTOCOL), 1)
        auth = hmac.new(self._secret_key, data, hashlib.sha1).digest()
        action_id = "%s.%s" % (base64.urlsafe_b64encode(auth), base64.urlsafe_b64encode(data))
        if len(action_id) > self._max_url_length:
            # Failover to session-based storage
            action_id = self._new_id()
            assert action_id not in self._all_actions
            self._all_actions[action_id] = action
            self._new_actions.append(action) # need to intern() page contexts later
        return action_id
    def _decode_action(self, action_id):
        """Convert the output of _encode_action() back into a real Action object.
        If the action_id is invalid, raises a TamperingError.
        """
        if "." in action_id: # action stored directly in URL
            auth, data = tuple(base64.urlsafe_b64decode(x) for x in str(action_id).split("."))
            if auth != hmac.new(self._secret_key, data, hashlib.sha1).digest():
                raise TamperingError("Signature does not match for %s" % action_id)
            action = pickle.loads(zlib.decompress(data))
            return action
        else: # action_id just a token for action we're storing
            action = self._all_actions.get(action_id)
            if action is None: raise TamperingError("Action %s not found" % action_id)
            return action
    @property
    def context(self):
        """The context object for the currently active page view."""
        return self._curr_page.context
    def start(self, request, handler, context=None):
        """No Action provided -- just display the given view.  Used e.g. for the start of a new session."""
        self._set_page(Page(handler, context, None), clone=False)
        try:
            self._rendering = True
            return self._curr_page(request, self)
        finally:
            self._rendering = False
    def run(self, request, action_id):
        """Run the provided action and display the resulting view."""
        action = self._decode_action(action_id)
        self._set_page(action.start_page, clone=True)
        action(request, self)
        try:
            self._rendering = True
            return self._curr_page(request, self)
        finally:
            self._rendering = False
    def do_goto(self, handler, context=None):
        """Change the current view, discarding the old view."""
        self._set_page(Page(handler, context, self._curr_page.parent), clone=False)
    def do_call(self, handler, context=None):
        """Change the current view, pushing the old view further down the stack."""
        self._set_page(Page(handler, context, self._curr_page), clone=False)
    def do_return(self):
        """Discard the current view and pop the previous view from the stack."""
        self._set_page(self._curr_page.parent, clone=True)
    def make_noop(self):
        """make_action() shortcut to re-display the current view with no changes."""
        return self.make_action(_handle_noop)
    def make_goto(self, handler, context=None):
        """make_action() shortcut to change the current view when clicked."""
        return self.make_action(_handle_goto, _dump_func(handler), context)
    def make_call(self, handler, context=None):
        """make_action() shortcut to change the current view when clicked."""
        return self.make_action(_handle_call, _dump_func(handler), context)
    def make_return(self):
        """make_action() shortcut to change the current view when clicked."""
        return self.make_action(_handle_return)
    def make_action(self, func, *args, **kwargs):
        """Make a URL-safe action "token" that will invoke the given function when token is passed to run()."""
        return self._encode_action(Action(func, self._curr_page, args, kwargs))
    def dumps(self):
        """Serialize this object to string form for storage in e.g. a session object.
        """
        # Page objects will proliferate wildly, but try to "intern()" their contexts, which may be large.
        def intern_pages(page):
            while page is not None:
                if page.context in self._all_contexts:
                    page.context = self._all_contexts[page.context]
                else:
                    self._all_contexts[page.context] = page.context
                page = page.parent
        curr_page, self._curr_page = self._curr_page, None # no reason to store this
        # Don't want these to get stored, particularly, but might need them in a minute.  Make a copy:
        new_actions = set(self._new_actions) # hash on object identity is all we need here
        self._new_actions = []
        # Pickle and compress everything, after interning.  If too big, drop the old ones and try again.
        for action in new_actions: intern_pages(action.start_page)
        data = zlib.compress(pickle.dumps(self, pickle.HIGHEST_PROTOCOL), 1)
        if self._size_limit is not None and len(data) > self._size_limit:
            # Oops!  Too big.  Wipe everything but the actions added this cycle.
            self._all_contexts.clear()
            for action_id, action in list(self._all_actions.iteritems()):
                if action not in new_actions:
                    del self._all_actions[action_id]
                else: intern_pages(action.start_page)
            # OK, re-encode remaining data
            data = zlib.compress(pickle.dumps(self, pickle.HIGHEST_PROTOCOL), 1)
        self._curr_page = curr_page # restore this so we can continue
        return data
    @staticmethod
    def loads(data):
        """Restore this object from storage."""
        return pickle.loads(zlib.decompress(data))

def _handle_noop(request, edwa):
    pass
def _handle_goto(request, edwa, handler, context):
    edwa.do_goto(_load_func(handler), context)
def _handle_call(request, edwa, handler, context):
    edwa.do_call(_load_func(handler), context)
def _handle_return(request, edwa):
    edwa.do_return()

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
    def __init__(self, handler, context=None, parent=None):
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
    def __call__(self, request, edwa):
        handler = _load_func(self.handler)
        return handler(request, edwa)
    def __cmp__(self, other):
        return cmp(self.__dict__, other.__dict__)
    def clone(self):
        """A semi-deep copy: deep copy of context, shallow copy of parent."""
        other = copy.copy(self)
        other.context = copy.deepcopy(self.context)
        return other

class Action(object):
    """Wrapper for an action function and its initial state.
    Like Pages, Actions must not be mutated once exposed to the web client."""
    def __init__(self, handler, start_page, args=None, kwargs=None):
        self.handler = _dump_func(handler)
        self.start_page = start_page
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
    def run(self):
        def show(action_id):
            print "    Action ID length:", len(action_id)
            return action_id
        # This is a very small size limit, designed to trigger the GC logic.
        # A real size limit of 100k or more seems advisable, unless your site is very heavily trafficked.
        edwa = EDWA("my-secret-key", size_limit=10000)
        edwa.start("<FAKE_REQUEST>", self.page1)
        edwa.run("<FAKE_REQUEST>", show(edwa.make_noop()))
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action3)))
        edwa.run("<FAKE_REQUEST>", show(edwa.make_call(self.page2)))
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action1)))
        edwa.run("<FAKE_REQUEST>", show(edwa.make_goto(self.page3)))
        for i in xrange(100): edwa.make_goto(self.page4)
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action1)))
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action2)))
        edwa.run("<FAKE_REQUEST>", show(edwa.make_return()))
        edwa.run("<FAKE_REQUEST>", show(edwa.make_return()))
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action1)))
        print "Suspending..."
        action_id = edwa.make_noop() # save current state
        edwa = EDWA.loads(edwa.dumps()) # pickle / unpickle
        print "Re-animating..."
        edwa.run("<FAKE_REQUEST>", action_id) # restore state (current view, etc)
        ## This makes encoding expensive (~ 1 sec), b/c it adds 100 large Action objects to be interned.
        for i in xrange(100): edwa.make_goto(self.page4)
        import time
        t_start = time.time()
        print "Storage size: %i bytes" % len(edwa.dumps())
        print "Time for encoding:", (time.time() - t_start), "seconds"
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
        edwa.do_call(self.page4, {"fizz":"buzz"})
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
