"""
A library of helper functions for working with and generating HTML as Unicode strings.

The Tagger class is inspired by Haml (http://haml-lang.com/) for Ruby.
Compared to Django templates, it's also much faster (as of Django 1.0.2),
although I haven't quantified "much" very accurately yet.
"""
from __future__ import print_function
from __future__ import with_statement
from future import standard_library
standard_library.install_aliases()
#from builtins import str
from past.builtins import basestring
from builtins import object
import sys

# I couldn't make things work properly with future.builtins.newstr, so we'll detect versions:
if sys.version[0] == 2:
    UNI_ENC = 'utf8'
    UNI_ERR = 'ignore'
    def to_unicode(x):
        """ Convert anything to unicode """
        return x if isinstance(x, unicode) else unicode(str(x), UNI_ENC, UNI_ERR)
else:
    def to_unicode(x):
        """ Convert anything to unicode """
        return x if isinstance(x, str) else str(x)

class raw(object):
    "A simple wrapper class to mark objects that should not be escaped."
    def __init__(self, obj):
        self.obj = obj

def escape(obj):
    "Escape HTML special chars in the string form of obj, unless obj is wrapped in raw()."
    if obj is None: return u"" # because the string "None" evaluates to True, while "" is False
    elif isinstance(obj, raw): return to_unicode(obj.obj)
    # Whitelist classes we know are safe to not escape, AND that have special printf formatting codes.
    # All others should be escaped for proper display (e.g. many objects use angle brackets in their str/repr form).
    elif isinstance(obj, (int,float)): return obj
    else: return to_unicode(obj).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')

def format_attrs(attrs):
    """Given a dictionary, format it to be included in an HTML tag.
    Names may include a trailing underscore to distinguish them from Python keywords (e.g. "class_"),
    and True and False may be used for logical attributes, like "checked" and "disabled".
    
    >>> format_attrs({'class_':'my-css-class', 'value':'<UNSAFE> & "VALUE"', 'checked':True, 'disabled':False})
    u" class='my-css-class' checked='checked' value='&lt;UNSAFE&gt; &amp; &quot;VALUE&quot;'"
    """
    attr_strs = []
    for name, value in attrs.items():
        name = name.rstrip("_") # e.g. allow "class_" instead of "class"
        if value is False or value is None: continue
        elif value is True: value = escape(name)
        else: value = escape(value)
        attr_strs.append(u" %s='%s'" % (name, value))
    return u"".join(attr_strs)

class Tag(object):
    """A supporting object for Tagger, representing one HTML tag.  Not used directly by clients."""
    def __init__(self, tagger, tagname, no_close=False):
        """If no_close is True, the tag will be like <BR /> instead of <BR>...</BR>."""
        self.tagger = tagger
        self.tagname = tagname
        self.no_close = no_close
        self.outer = None # another tag that encloses this one!
        self.attrs = {}
    def __enter__(self):
        "Write the opening tag."
        # I don't think the inner/outer nesting here actually preserves
        # the full behavior of contextlib.nested(), but it should be good enough.
        outer = self.outer
        if outer is not None:
            retval = outer.__enter__()
            if isinstance(retval, tuple): retval = retval + (self,)
            else: retval = (retval, self)
        t = self.tagger
        t._indent()
        # no_close doesn't really make sense in a with block,
        # but __enter__ and __exit__ are also used by __call__ (where it does make sense).
        if self.no_close:
            t._raw(u"<%s%s />" % (self.tagname, format_attrs(self.attrs)))
        else:
            t._raw(u"<%s%s>" % (self.tagname, format_attrs(self.attrs)))
            t._depth += 1
        if outer is not None: return retval
        else: return self
    def __exit__(self, exc_type, exc_value, traceback, indent=True):
        "Write the closing tag."
        t = self.tagger
        if not self.no_close:
            t._depth -= 1
            if indent: t._indent()
            t._raw(u"</%s>" % self.tagname)
        outer = self.outer
        if outer is not None: return outer.__exit__(exc_type, exc_value, traceback)
    def __call__(self, content_or_fmtstr=None, fmtvars=None, **kwargs):
        """Supports several nearly-conflicting behaviors!
        
        tag("some message")
            Writes its argument to the tagger, wrapped in opening and closing tags,
            escaping any special chars.
            
        tag("%(foo)s = %(bar)i", vals)
            Escapes the values in dictionary or tuple "vals", does string interpolation,
            and then writes the result wrapped in opening and closing tags, without further escaping.
            (That is, the format string is expected to be HTML-safe already.)
            
        tag(class_="my-css-class", checked=True):
            Updates self.attrs and returns self, for use in a with statement.
        """
        t = self.tagger
        self.attrs.update(kwargs)
        if content_or_fmtstr is not None:
            self.__enter__()
            t(content_or_fmtstr, fmtvars, indent=False)
            self.__exit__(None, None, None, indent=False)
        return self
    def __getattr__(self, x):
        "Allows chaining of tags created by Tagger."
        inner = getattr(self.tagger, x)
        inner.outer = self
        return inner
        
# TODO: add other doctypes below
HTML4_STRICT = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">'

_NOCLOSE_TAGS = set(["base", "br", "hr", "img", "input", "link", "meta"])

class Tagger(object):
    """The public interface to tag generation via the "with" statement."""
    def __init__(self, buffer=None, indent=None, doctype=HTML4_STRICT):
        "If indent is set to a number, each tag level will be indented by that many more spaces."
        if buffer is None:
            from io import StringIO
            buffer = StringIO()
        self._buffer = buffer
        self._raw = buffer.write # a function!
        self._indent_depth = indent
        self._depth = 0
        self._raw(doctype)
    def _indent(self):
        i = self._indent_depth
        if i is not None:
            self._raw(u"\n")
            self._raw(u" " * (i*self._depth))
    def __call__(self, content_or_fmtstr, fmtvars=None, indent=True):
        if indent: self._indent()
        if fmtvars is None:
            self._raw(escape(content_or_fmtstr))
        else:
            if hasattr(fmtvars, "iteritems"):
                fmtvars = dict((k, escape(v)) for k, v in fmtvars.items())
            elif isinstance(fmtvars, basestring):
                fmtvars = escape(fmtvars)
            else:
                try: fmtvars = tuple(escape(v) for v in fmtvars)
                except TypeError: fmtvars = escape(fmtvars) # guess it wasn't iterable after all! (int, bool, etc.)
            self._raw(to_unicode(content_or_fmtstr) % fmtvars)
    def __getitem__(self, raw_content):
        """A total abuse of notation: use [] to output un-escaped HTML."""
        self(raw(raw_content))
    def __getattr__(self, tagname):
        return Tag(self, tagname, no_close=(tagname.lower() in _NOCLOSE_TAGS))

def testit():
    t = Tagger(indent=1)
    with t.html:
        with t.head:
            t.title('This is my "great" page')
        with t.body:
            t.p(class_='speech').b.u.i("Fourscore & seven years ago...", id='id_speech_text')
            with t.table.tr(align='center'):
                t.td("<UNSAFE>")
                t.td("%.3f", 2.7182818)
                t.td.b("---%s---", "1 & 2")
                t.td("%s, %s, %.2f", ("One", "<II>", 3.14159))
                t.td("Hello %(othername)s, I'm %(selfname)s", {"othername":"'Foo'", "selfname":raw("'Bar'")})
            t(raw("<input type='hidden' name='foo' value='bar'>"))
    print(t._buffer.getvalue())

if __name__ == "__main__":
    import doctest
    doctest.testmod()
