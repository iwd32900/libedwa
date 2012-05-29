"""
A library for Event-Driven Web Applications (EDWA).
Please see the README file for explanation!
"""
import base64, hashlib, hmac, sys
try: import cPickle as pickle
except ImportError: import pickle

# Zlib compressing appears to be a very small net win in size for simple pages.
# For contexts with lots of English text, though, it may help more?
# Bzip2 compression makes things worse for such small amounts of data.
from zlib import compress, decompress
#from bz2 import compress, decompress
#compress = decompress = lambda x, lvl=0: x

SEP = b'.' # works as early as 2.6

__all__ = ['EDWA', 'TamperingError']

def _dump_func(f):
    """Given a module-level or instance function, convert to a picklable form."""
    if f is None: return None
    if hasattr(f, "im_class"): return ".".join((f.__module__, f.im_class.__name__, f.__name__)) # works in 2.x but not 3.x
    elif hasattr(f, "__self__"): return ".".join((f.__module__, f.__self__.__class__.__name__, f.__name__)) # works in 3.x and 2.7, but not earlier
    else: return ".".join((f.__module__, f.__name__))

def _load_func(x):
    """Restore a usable function from the results of _dump_func()."""
    if x is None: return None
    names = x.split(".")
    # Try first 1, 2, ... names as the module name.
    # (Is it possible to import "foo.bar" without also importing "foo"?)
    module = None
    for ii in range(len(names)):
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

    View functions should be defined as:
    def render(request, edwa):
        # make some links with href_goto(), etc.
        return HttpResponse("<html>...</html>")

    Event handlers should be defined as:
    def handle_event(request, edwa):
        # do_goto(), edwa.context.foo = bar, etc.
        # nothing to return

    Return value handlers, if used, should be defined as:
    def on_return(edwa, return_value, return_context):
        # return_value is provided by the page that's returning
        # return_context was provided at the time of the original call
        # do_goto(), edwa.context.foo = return_value, etc.
        # nothing to return
    """
    PAGE_KEY = "edwa.page"
    ACTION_KEY = "edwa.action"
    POST_KEY = "edwa.did_post" # used to distinguish EDWA hidden form from user forms
    MODE_RENDER = ['render'] # just a unique object instance, use "is"
    MODE_ACTION = ['action'] # just a unique object instance, use "is"
    def __init__(self, secret_key, use_GET=False):
        assert secret_key, "Must provide a non-empty secret key!"
        # Configuration
        if not isinstance(secret_key, bytes): secret_key = secret_key.encode() # Unicode -> bytes
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
    @property
    def tmp(self):
        """Just like context, but not preserved across requests.
        A convenience for passing transient data between the action and the view."""
        return self._curr_page.tmp
    def _typecheck_str(self, s):
        """This class deals only with ASCII / byte strings, while others prefer Unicode."""
        if not isinstance(s, bytes): return s.encode()
        else: return s
    def _set_page(self, page):
        """Set the current page to some newly-created Page object."""
        assert self._mode is not EDWA.MODE_RENDER, "Can't change location during rendering!  Did you mean to call make_*()?"
        assert page is not None
        self._curr_page = page
        self._curr_page_encoded = None
    def _encode_page(self):
        assert self._curr_page is not None
        self._curr_page_encoded = base64.urlsafe_b64encode(compress(self._curr_page.encode()))
    def _decode_page(self):
        """In this implementation, the page data itself is not signed; it's signed in combination with an action.
        So you want to make sure the action has been verified before decoding the page, or it opens you to attacks against pickle."""
        assert self._curr_page_encoded is not None
        self._set_page(Page.decode(decompress(base64.urlsafe_b64decode(self._curr_page_encoded))))
    def _encode_action(self, action):
        """Encode the Action directly as a URL.  Must be paired with page data when passed to run()."""
        assert self._mode is not EDWA.MODE_ACTION, "Can't create new actions during an action, because page state is not finalized."
        assert self._curr_page_encoded is not None, "Page state must be serialized before creating an action!"
        data = base64.urlsafe_b64encode(compress(action.encode(), 1))
        auth = hmac.new(self._secret_key, data + SEP + self._curr_page_encoded, hashlib.sha1).digest()
        return base64.urlsafe_b64encode(auth) + SEP + data
    def _decode_action(self, action_id):
        """Convert the output of _encode_action() back into a real Action object.
        If the action_id is invalid, raises a TamperingError.
        """
        assert self._curr_page_encoded is not None, "Page state must be known when decoding an action!"
        if SEP not in action_id: raise TamperingError("Malformed action_id %s" % action_id)
        auth, data = action_id.split(SEP, 1)
        if base64.urlsafe_b64decode(auth) != hmac.new(self._secret_key, data + SEP + self._curr_page_encoded, hashlib.sha1).digest():
            raise TamperingError("Signature does not match for %s" % action_id)
        action = Action.decode(decompress(base64.urlsafe_b64decode(data)))
        return action
    def start(self, request, handler, context=None, render=True):
        """No Action provided -- just display the given view.  Used e.g. for the start of a new session."""
        self._set_page(Page(handler, context, None))
        if render: return self.render_page(request)
    def run(self, request, action_id, page_id, render=True):
        """Run the provided action and display the resulting view."""
        action_id = self._typecheck_str(action_id)
        page_id   = self._typecheck_str(page_id)
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
        if render: return self.render_page(request)
    def render_page(self, request):
        """Display the current page state.  Call start() or run() first, with render=False."""
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
            # quotes need to be escaped; this works for href="..." and href='...'
            return 'javascript:libedwa_post_href(\"%s\");' % action_id # will trigger a POST of a hidden form via JavaScript
    # Shortcuts for form(make_XXX()):
    def form_noop(self): return self.form(self.make_noop())
    def form_goto(self, *args, **kwargs): return self.form(self.make_goto(*args, **kwargs))
    def form_call(self, *args, **kwargs): return self.form(self.make_call(*args, **kwargs))
    def form_return(self, *args, **kwargs): return self.form(self.make_return(*args, **kwargs))
    def form_action(self, *args, **kwargs): return self.form(self.make_action(*args, **kwargs))
    def form(self, action_id):
        """Convenience function to create the needed hidden <INPUT> fields in a user form.
        Typical use in Django: <form> {% raweval edwa.form(edwa.make_action(...)) %} </form>"""
        return r"""<input type='hidden' name='%(pkey)s' value='%(pdata)s'>
<input type='hidden' name='%(akey)s' value='%(adata)s'>
""" % {'pkey':self.PAGE_KEY, 'pdata':self.make_page_data(), 'akey':self.ACTION_KEY, 'adata':action_id}
    def hidden_form(self):
        """Create a hidden FORM and some JavaScript for an HTML page, to enable the href() helper function.
        Should be placed at the very end of the page, just before </BODY>, after all <A> links!
        Typical use in Django: {{ edwa.hidden_form|safe }} </BODY> </HTML>
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
<input type='hidden' name='%(postkey)s' value='1'>
<input type='hidden' name='%(pkey)s' value='%(pdata)s'>
<input type='hidden' id='__libedwa__.action_id' name='%(akey)s' value=''>
</form>
""" % {'postkey':self.POST_KEY, 'pkey':self.PAGE_KEY, 'pdata':self.make_page_data(), 'akey':self.ACTION_KEY}

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
        self.handler = _load_func(_dump_func(handler)) # create class instance if needed
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
        self.return_handler = _load_func(_dump_func(return_handler))
        self.return_context = return_context
        # .tmp is just like .context, except it is not pickled and restored:
        self.tmp = Context()
    def encode(self):
        data = [_dump_func(self.handler),
                (dict(self.context) if len(self.context) else None),
                (self.parent.encode() if self.parent is not None else None),
                _dump_func(self.return_handler),
                self.return_context]
        while data[-1] is None: data.pop() # remove trailing None's to save space
        return pickle.dumps(data, pickle.HIGHEST_PROTOCOL)
    @classmethod
    def decode(cls, encoded):
        data = pickle.loads(encoded)
        while len(data) < 5: data.append(None) # restore trailing None's
        data[0] = _load_func(data[0])
        if data[2] is not None: data[2] = cls.decode(data[2])
        if data[3] is not None: data[3] = _load_func(data[3])
        return cls(*data)
    def __call__(self, request, edwa):
        return self.handler(request, edwa)
    def on_return(self, edwa, return_value):
        # edwa.context will be the context of the returned-to page (self.parent.context), not self.context
        if self.return_handler is not None:
            self.return_handler(edwa, return_value, self.return_context)
    def __cmp__(self, other):
        return cmp(self.__dict__, other.__dict__)

class Action(object):
    """Wrapper for an action function and its initial state."""
    def __init__(self, handler, args=None, kwargs=None):
        self.handler = _load_func(_dump_func(handler)) # create class instance if needed
        self.args = args or []
        self.kwargs = kwargs or {}
    def encode(self):
        data = [_dump_func(self.handler),
                self.args or None,
                self.kwargs or None]
        while data[-1] is None: data.pop() # remove trailing None's to save space
        return pickle.dumps(data, pickle.HIGHEST_PROTOCOL)
    @classmethod
    def decode(cls, encoded):
        data = pickle.loads(encoded)
        while len(data) < 3: data.append(None) # restore trailing None's
        data[0] = _load_func(data[0])
        return cls(*data)
    def __call__(self, request, edwa):
        return self.handler(request, edwa, *self.args, **self.kwargs)
