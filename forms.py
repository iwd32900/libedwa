"""
Form-helper library inspired by django.forms, but addressing the following issues:

- Dynamic forms are hard, because Django defaults to a declarative style.
  We use an imperative style of adding inputs to an initially empty Form object,
  which is nearly as terse and much more flexible.  No subclassing is required.

- Dynamic forms are hard, because initialization values are also coded declaratively.
  This particularly affects HTML <select> elements when the choices come from a database.
  Again, our imperative approach makes this easy.

- Widgets are awkward to customize, because the primary form classes are organized
  around validating the data, rather than around the HTML elements used to gather the data.
  This is wrong:  the set of possible HTML elements is small and fixed,
  but the set of possible ways to validate that input and make Python objects is infinite.
  We focus on a one-to-one mapping with HTML elements, and allow data transformation and validation
  to be configured by passing in (lists of) functions.
  As a side effect, this makes it easier to add and validate new constraints on form inputs.

- Django forms behave differently whether they are "bound" or "unbound";
  specifically, validation is triggered just by passing in POST data.
  We use the same mechanism to pass initial values or POST data,
  and trigger validation (and display of errors) explicitly by calling Form.validate().

- Django forms are really designed to display using the built-in .as_p(), .as_table(), etc. functions;
  accessing individual components (particularly radio buttons from a set of them!) is tough.
  We try to design forms so that individual elements are easy to access and display in any way desired.
  We offer helpers like as_table() as standalone functions that take a Form as an argument,
  so that end-users can construct similar display helpers using the same public API we do.

For example code, see libedwa.django_demo.views.
"""

from libedwa.html import escape, raw, format_attrs

def is_scalar(x):
    """False if x is a list-like iterable (list, tuple, etc.), but True if x is a string or other scalar."""
    if isinstance(x, basestring): return True
    if hasattr(x, "keys") and hasattr(x, "values"): return True
    try:
        iter(x)
        return False
    except TypeError:
        return True

def as_vector(x):
    """If x is a scalar or non-indexable iterator, wrap it in a list."""
    if is_scalar(x): return [x]
    try:
        len(x)
        return x
    except TypeError:
        return list(x)

class Form(object):
    """Basic HTML form.  To add fields, use "+=" rather than trying to subclass.  See set_data() for "data" and "files"."""
    def __init__(self, action="", data={}, files={}, method="POST", prefix="", id_prefix="id_", **kwargs):
        """
        data    see set_data()
        """
        self.action = action
        self.method = method
        self.prefix = prefix
        self.id_prefix = id_prefix
        self.attrs = kwargs
        self.children = []
        self.by_name = {} # for random access to `children`
        self.set_data(data=data, files=files)
    def set_data(self, data={}, files={}):
        """
        data    A dictionary mapping HTML names (as strings) to lists of values.
                Bare, non-list values will automatically be wrapped in lists.
                This can either be initial values, or the result of form submission.
                Calling this function replaces any values passed previously or in the constructor,
                and overrides any values passed to individual inputs as initial=...
                In Django, try dict(request.POST.lists()).
                In Bottle, try request.forms.dict.
        files   A dictionary mapping HTML names (as strings) to file-like objects.
                These will be wrapped in lists (like data) for consistency sake.
                In Django, try request.FILES.
                In Bottle, try request.files.dict.
        """
        data = data or {} # in case None is passed
        if files:
            data = dict(data) # make a copy
            data.update(files) # include info about uploaded files
        # Make sure keys are prefixed with the form-wide prefix.
        # Make sure values are lists -- convert bare values into single-item lists.
        self.data = dict(((k if k.startswith(self.prefix) else self.prefix+k), as_vector(v)) for k, v in data.iteritems())
    def add(self, child):
        """Add a new input component to this form."""
        self.children.append(child)
        self.by_name[child._name] = child
        return self # needed to support "+=" syntax
    __iadd__ = add # so you can use "form += input_element"
    def __iter__(self):
        """Iterate over the components in this form."""
        return iter(self.children)
    def __getitem__(self, k):
        """Return child components by name."""
        return self.by_name[k]
    def html(self):
        """Generate the opening FORM tag (only)."""
        attrs = dict(self.attrs)
        if any(isinstance(child, FileInput) for child in self.children):
            attrs["enctype"] = "multipart/form-data"
        return u"<form id='%s%s_form' action='%s' method='%s'%s>" % (self.id_prefix, self.prefix, escape(self.action), self.method, format_attrs(attrs))
    def validate(self):
        """
        Returns true iff all form components validate (i.e., have no errors).
        Calling validate() will cause error messages to be displayed with the form.
        """
        valid = True
        for child in self.children:
            valid &= child.validate()
        return valid
    def rawvalues(self):
        """Returns a dictionary mapping input names (without the prefix)
        to values or lists of values, depending on their type.
        The dictionary is re-generated on the fly each time the function is called,
        so you may want to save it to a variable before using."""
        return dict((child._name, child.rawvalue) for child in self.children)
    def values(self):
        """Returns a dictionary mapping input names (without the prefix)
        to values or lists of values, depending on their type.
        This is likely incomplete unless validate() returns True.
        The dictionary is re-generated on the fly each time the function is called,
        so you may want to save it to a variable before using."""
        return dict((child._name, child.value) for child in self.children)
    def errors(self):
        """Returns a dictionary mapping input names (without the prefix)
        to lists of error messages.  Only inputs with errors are included,
        so if validate() return True, this should be an empty dict."""
        return dict((child._name, child.errors) for child in self.children if child.errors)

### Various types of input objects to use in Forms ###

class Input(object):
    """Abstract base object for all form inputs."""
    def __init__(self, form, name, **kwargs):
        """
        form        the Form this input will belong to
        name        the value for the name="..." attribute
        id_postfix  optional postfix for HTML id field to ensure global uniqueness (used by RadioSelect and CheckboxSelect)
        label       a human-readable name for this field
        help_text   a hint for the person filling out the field
        type        callable that takes a single string and returns a Python object
                    Throwing an exception results in a value of None.
                    If type.untype exists, it will be called on the results of rawvalue before they are returned.
                    This allows rawvalue to format objects (e.g. datetimes) as strings,
                    in a form that can later be parsed by type() to recreate the object.
                    Type.untype() is only needed when "initial=object" and "object != type(str(object))".
                    It will sometimes be passed strings (so it should do nothing), and will get scalars, not lists.
                    See DateTime (below) for an example.
        require     a list of validation functions, which take one argument (the value)
                    and return either an error message (as a string) or None if the value is OK.
                    Most validators should allow None as a valid value.
                    NEW: validator functions should also accept **kwargs, which *may* include:
                        peers   a dictionary {name:Input} of other Inputs in the parent form.
                                Usually built from self.form.children (though not for NestedForms).
        required    if True (the default), prepends not_empty to the list of requirements for validation.
        initial     a fallback initial value if no data is provided to the Form
                    If *any* data is provided to the form, the initial value is ignored,
                    even though there may be no value for *this* input in the form data.
                    (This is to allow e.g. checkboxes that default to True to still be set to False.)
        **kwargs    any HTML attributes that should be included, e.g. disabled=True, class_='my-css-style'
        """
        self.form = form
        self._name = name # base name, without form prefix
        self.name = form.prefix + name # HTML name attribute, with form-wide prefix
        self.id = form.id_prefix + self.name + kwargs.pop("id_postfix", "")
        self.label = kwargs.pop("label", name.replace("_", " ").capitalize())
        self.help_text = kwargs.pop("help_text", None)
        self.type = kwargs.pop("type", unicode)
        self.require = kwargs.pop("require", [])
        self.required = kwargs.pop("required", True)
        if self.required: self.require = [not_empty] + self.require
        if "initial" in kwargs: self._initial = kwargs.pop("initial")
        self.attrs = kwargs
        self.errors = None # list of error messages, if any, not yet escaped for HTML special chars
    @property
    def rawvalue(self):
        """The value as provided to the Form, without any kind of transformation or validation."""
        raise NotImplementedError()
    @property
    def value(self):
        """The standardized, validated value of the component, or None if validation fails.
        Accessing value will cause error messages to be displayed with this field."""
        # If we've already computed our value, just return it.
        if hasattr(self, "_value"):
            return self._value
        # Enter validation mode. Start accumulating error messages.
        self.errors = []
        # Try to coerce the string form into a Python object.
        # Do not escape error messages here: they will be escaped before output.
        # This means they're still readable for e.g. console output.
        try:
            self._value = self.objectify(self.rawvalue)
        except Exception, ex:
            self._value = None
            # Type conversion failure on the empty value is OK (maybe, see require=[not_empty]),
            # but type conversion failure on a non-empty value is an error.
            if self.rawvalue:
                self.errors.append(unicode(ex))
                # Although most validators allow None, so we wouldn't *have* to short-circuit,
                # validators like not_empty will produce a confusing value in response to this None.
                return self._value
        # If coerced successfully, apply the 'require' criteria (if any).
        peers = dict((inp._name, inp) for inp in getattr(self, "peers", self.form.children))
        for requirement in self.require:
            try: err = requirement(self._value, peers=peers)
            except TypeError: err = requirement(self._value) # old-style validator doesn't take **kwargs
            if err: self.errors.append(unicode(err))
        if self.errors: self._value = None
        return self._value
    def objectify(self, value):
        """Convert the raw value into the standarized value, using self.type."""
        raise NotImplementedError()
    def html(self):
        """Render the component as an HTML string."""
        raise NotImplementedError()
    def validate(self):
        """Checks to see if this control has errors in interpretting its value."""
        self.value
        if not is_scalar(self):
            for child in self: child.value
        return not self.errors

class ScalarInput(Input):
    """Any form component that takes on at most one value."""
    @property
    def rawvalue(self):
        val = u""
        if self.name in self.form.data:
            val = self.form.data[self.name]
        # Only fall back to our internal default if no POST data was provided:
        elif hasattr(self, "_initial") and not self.form.data:
            val = self._initial
        if not is_scalar(val): val = val[-1] # if multiple values, return the last one! (like Django)
        if hasattr(self.type, "untype"):
            val = self.type.untype(val)
        return val
    def objectify(self, value):
        return self.type(value)

class TextInput(ScalarInput):
    def html(self):
        return u"<input type='text' id='%s' name='%s' value='%s'%s />" % (self.id, self.name, escape(self.rawvalue), format_attrs(self.attrs))

class Textarea(ScalarInput):
    def html(self):
        return u"<textarea id='%s' name='%s'%s>%s</textarea>" % (self.id, self.name, format_attrs(self.attrs), escape(self.rawvalue))

class PasswordInput(ScalarInput):
    def html(self):
        #return u"<input type='password' id='%s' name='%s' value='%s'%s />" % (self.id, self.name, escape(self.rawvalue), format_attrs(self.attrs))
        # A password field should never be pre-filled server side.  Among other things, it ends up in the browser cache.
        # If there's an error in form validation, you have to retype the password -- sorry.
        return u"<input type='password' id='%s' name='%s'%s />" % (self.id, self.name, format_attrs(self.attrs))

class HiddenInput(ScalarInput):
    def html(self):
        return u"<input type='hidden' id='%s' name='%s' value='%s'%s />" % (self.id, self.name, escape(self.rawvalue), format_attrs(self.attrs))

class FileInput(ScalarInput):
    """Provides either a file(-like) object, or None."""
    def __init__(self, form, name, **kwargs):
        def file_type(x):
            # cgi.FieldStorage objects are provided by Bottle.
            # They're irritating to work with, and for some reason evaluate to False (!)
            import cgi
            if isinstance(x, cgi.FieldStorage):
                if x.file: return x.file
                else:
                    import cStringIO as StringIO
                    return StringIO.StringIO(x.value)
            # Django kindly provides file-like objects to start with, which evaluate as True.
            elif x: return x
            else: return None
        kwargs["type"] = file_type
        super(FileInput, self).__init__(form, name, **kwargs)
    def html(self):
        return u"<input type='file' id='%s' name='%s'%s />" % (self.id, self.name, format_attrs(self.attrs))

class BooleanInput(ScalarInput):
    """A control that returns False when unchecked, and a specified non-false value when checked.
    Unlike most controls, these controls are not required by default."""
    def __init__(self, form, name, value=True, **kwargs):
        kwargs["type"] = bool
        kwargs.setdefault("required", False) # unless specifically set to True by the caller
        super(BooleanInput, self).__init__(form, name, **kwargs)
        self.checked_value = value
    @property
    def rawvalue(self):
        """A little different from most inputs: rawvalue is True or False."""
        to_search = []
        if self.name in self.form.data:
            to_search = self.form.data[self.name]
        # Only fall back to our internal default if no POST data was provided:
        elif hasattr(self, "_initial") and not self.form.data:
            to_search = as_vector(self._initial)
        strval = unicode(self.checked_value)
        # Testing "formval is True" allows us to use initial=True
        # This should be safe because POST data can only be strings, not Python True.
        val = any((strval == unicode(formval) or formval is True) for formval in to_search)
        # Deliberately ignores self.type.untype, even if it's present.
        return bool(val)
    @property
    def value(self):
        """A little different from most inputs: value is the fixed value passed to constructor or None."""
        # This doesn't do much, but at least ensures errors[] is populated.
        # Although there aren't many things you can require for a checkbox...
        if super(BooleanInput, self).value:
            return self.checked_value
        else: return False
    def html(self):
        attrs = dict(self.attrs)
        attrs['checked'] = bool(self.rawvalue) # don't want to trigger validation
        return u"<input type='%s' id='%s' name='%s' value='%s'%s />" % (self.input_type, self.id, self.name, escape(self.checked_value), format_attrs(attrs))

class CheckboxInput(BooleanInput):
    input_type = "checkbox"

class RadioInput(BooleanInput):
    """Single radio buttons really aren't useful.  You want RadioSelect instead."""
    input_type = "radio"

class Button(BooleanInput):
    def __init__(self, form, label, name="-submit", **kwargs):
        """Note that the order of arguments varies from all the other inputs!
        This is so it will do what you want in the most common case (defining a submit button).
        Use "name" and "value" to define what gets submitted with the HTML form,
        use "label" to define what the user sees.

        action      "submit" (the default) or "reset"
        """
        self.action = kwargs.pop("action", "submit")
        super(Button, self).__init__(form, name, label=label, **kwargs)
        self.label, self._label = "", self.label # "hide" label for display
    def html(self):
        return u"<button type='%s' id='%s' name='%s' value='%s'%s>%s</button>" % (self.action, self.id, self.name, escape(self.checked_value), format_attrs(self.attrs), self._label)

class VectorInput(Input):
    single_selection = False
    @property
    def rawvalue(self):
        val = []
        if self.name in self.form.data:
            val = self.form.data[self.name]
        # Only fall back to our internal default if no POST data was provided:
        elif hasattr(self, "_initial") and not self.form.data:
            val = as_vector(self._initial)
        if hasattr(self.type, "untype"):
            fmt = self.type.untype
            val = [fmt(v) for v in val]
        return val
    @property
    def value(self):
        val = super(VectorInput, self).value
        if val is not None and len(val) == 1 and self.single_selection:
            val = val[0]
        return val
    def objectify(self, value):
        return [self.type(v) for v in value]

class Choice(object):
    """An option to be used in a ChoiceInput subclass."""
    def __init__(self, value, label=None):
        self.value = value
        self.label = label or value

class ChoiceInput(VectorInput):
    """
    choices     Either a list of Choice objects, or a list of simple values,
                or a list of (value, human_readable) tuples.
    """
    def __init__(self, form, name, **kwargs):
        choice_list = kwargs.pop('choices', [])
        super(ChoiceInput, self).__init__(form, name, **kwargs)
        self.choices = []
        for choice in choice_list:
            if isinstance(choice, Choice): pass
            elif isinstance(choice, (list,tuple)): choice = Choice(*choice)
            else: choice = Choice(choice)
            if choice.value != self.type(choice.value):
                raise ValueError("Choice (%r, %r) is type %s, not type %s" % (choice.value, choice.label, type(choice.value), self.type))
            self.choices.append(choice)
        self.require.append(in_choices(self.choices))

class Select(ChoiceInput):
    """Defaults to single selection -- include multiple=True to allow multiple selection."""
    def __init__(self, form, name, **kwargs):
        self.single_selection = not kwargs.get("multiple", False)
        super(Select, self).__init__(form, name, **kwargs)
    def html(self):
        selected = set(unicode(v) for v in self.rawvalue)
        lines = []
        lines.append(u"<select id='%s' name='%s'%s>" % (self.id, self.name, format_attrs(self.attrs)))
        for choice in self.choices:
            val = unicode(choice.value)
            is_selected = (u" selected='selected'" if val in selected else u"")
            lines.append(u"<option value='%s'%s>%s</option>" % (escape(choice.value), is_selected, escape(choice.label)))
        lines.append(u"</select>")
        return u"\n".join(lines)

class ChildSelect(ChoiceInput):
    """
    Base for selection elements that use multiple HTML elements as children.
    """
    def __init__(self, form, name, **kwargs):
        super(ChildSelect, self).__init__(form, name, **kwargs)
        kwargs.pop("label", None)
        intial = kwargs.pop("initial", object())
        # if initial is not set, no choice value can ever equal this particular anonymous object
        self.children = [self.InputClass(form, name, type=self.type, value=choice.value, initial=(choice.value if choice.value == intial else object()),
                label=choice.label, id_postfix=("__%i" % ii), **self.attrs) for ii, choice in enumerate(self.choices)]
        # dots are technically legal in HTML id's, but jQuery doesn't tolerate them
        self.by_value = dict((c.checked_value, c) for c in self.children) # for random access to `children` by their value
    def __iter__(self):
        for child in self.children: yield child
    def __getitem__(self, k):
        """Return child components by value."""
        return self.by_value[k]

class RadioSelect(ChildSelect):
    """Although this derives from VectorInput, only one radio can be selected at a time.
    Thus, it returns a scalar value when a radio is selected.
    It returns the empty list when no radios are selected."""
    single_selection = True
    InputClass = RadioInput

class CheckboxSelect(ChildSelect):
    InputClass = CheckboxInput

### Input types for use with type=... ###

# Be careful of listing too many, because DATE_TIME_FMTS includes all combinations of the two!
DATE_FMTS = ["%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%d %b %Y"] # 2006-10-25; 10/25/2006; Oct 25, 2006; 25 Oct 2006
TIME_FMTS = ["%H:%M:%S", "%H:%M", "%I:%M:%S%p", "%I:%M:%S %p", "%I:%M%p", "%I:%M %p"] # 14:30:59; 14:30; 2:30:59pm; 2:30:59 pm; 2:30pm; 2:30 pm (am,pm == AM,PM)
DATE_TIME_FMTS = [" ".join((d, t)) for d in DATE_FMTS for t in TIME_FMTS] + [" ".join((t, d)) for d in DATE_FMTS for t in TIME_FMTS] # "date time", then "time date"

def as_date_or_time(x):
    """'x' should be a date, time, or datetime object from the datetime module,
    or a string matching one of the default allowed formats."""
    if not isinstance(x, basestring): return x
    import datetime as dt
    # Try simple date and time first, because there are fewer of those to check!
    for format in DATE_FMTS:
        try: return dt.datetime.strptime(x, format).date()
        except ValueError: pass
    for format in TIME_FMTS:
        try: return dt.datetime.strptime(x, format).time()
        except ValueError: pass
    for format in DATE_TIME_FMTS:
        try: return dt.datetime.strptime(x, format)
        except ValueError: pass
    raise ValueError("Cannot interpret '%s' as a date/time" % x)

def DateTime(formats=DATE_TIME_FMTS, err_fmt="Cannot interpret '%s' as a date + time"):
    formats = as_vector(formats)
    def maketype(text):
        import datetime as dt
        for format in formats:
            try: return dt.datetime.strptime(text, format)
            except ValueError: pass
        raise ValueError(err_fmt % text)
    def untype(obj): # so that datatime objs can be provided to initial=...
        try: return obj.strftime(formats[0])
        except: return obj
    maketype.untype = untype # yes Virginia, you *can* do that to a Python function!
    return maketype

def Date(formats=DATE_FMTS):
    f = DateTime(formats, err_fmt="Cannot interpret '%s' as a date")
    def maketype(text):
        return f(text).date()
    maketype.untype = f.untype
    return maketype

def Time(formats=TIME_FMTS):
    f = DateTime(formats, err_fmt="Cannot interpret '%s' as a time of day")
    def maketype(text):
        return f(text).time()
    maketype.untype = f.untype
    return maketype

### Validation functions to use with require=[...] ###

def not_empty(val, **kwargs):
    """A mandatory, non-empty form field."""
    # This is surprisingly hard to get right.
    # Zero is a legit value but "not 0" is true.
    # Also 0 == False and 0 in [False, ...] are both true (!)
    # However "0 is False" is false, as expected
    if val is None or val is False or val in ("", u"", [], tuple(), {}):
        return "This field is required"

def regex(r, error_msg=None):
    """
    A regular expression object or string that input must match.
    re.search() will be called, so anchor with ^ and $ if desired.
    The empty string will always be allowed, so pair with not_empty to prevent this.
    """
    if isinstance(r, basestring):
        import re
        r = re.compile(r)
    def validate(val, **kwargs):
        if not val: return # allow field to be empty, including the empty string
        if not r.search(val):
            if error_msg: return error_msg
            else: return "Please enter a value matching /%s/" % r.pattern
    return validate

slug = regex( # just to be like Django...
    r'^[-\w]+$',
    "Please enter a slug (letters, numbers, hyphens, and/or underscores)")

email = regex( # blatantly stolen from Django
    r"^(?i)([-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"  # dot-atom
    r'|"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-011\013\014\016-\177])*"' # quoted-string
    r')@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?$',  # domain
    "Please enter an email address")

web_url = regex( # also blatantly stolen from Django
    r'^(?i)https?://' # http:// or https://
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|' #domain...
    r'localhost|' #localhost...
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
    r'(?::\d+)?' # optional port
    r'(?:/?|[/?]\S+)$',
    "Please enter a URL, starting with http:// or https://")

def maximum(m):
    """Maximum numeric value, inclusive."""
    def validate(val, **kwargs):
        if val is None: return # allow field to be empty
        if val > m: return "Please enter a value of at most %s" % m
    return validate

def minimum(m):
    """Minimum numeric value, inclusive."""
    def validate(val, **kwargs):
        if val is None: return # allow field to be empty
        if val < m: return "Please enter a value of at least %s" % m
    return validate

def maxlen(m):
    """Maximum string length, inclusive."""
    def validate(val, **kwargs):
        if val is None: return # allow field to be empty
        if len(val) > m: return "Please limit to %s characters" % m
    return validate

def minlen(m):
    """Minimum string length, inclusive.  Empty string *is* permitted, unless paired with not_empty."""
    def validate(val, **kwargs):
        if not val: return # allow field to be empty, including the empty string
        if len(val) < m: return "Please enter at least %s characters" % m
    return validate

def not_before(x):
    """Set limits on date and/or time. See as_date_or_time() for possible values of x."""
    dt = as_date_or_time(x)
    def validate(val, **kwargs):
        if val is None: return # allow field to be empty
        if val < dt: return "Please enter a date/time of %s or later" % x
    return validate

def not_after(x):
    """Set limits on date and/or time. See as_date_or_time() for possible values of x."""
    dt = as_date_or_time(x)
    def validate(val, **kwargs):
        if val is None: return # allow field to be empty
        if val > dt: return "Please enter a date/time of %s or earlier" % x
    return validate

def each(requirement):
    """Wrapper to turn validators that expect scalars into validators that expect lists."""
    def validate(values, **kwargs):
        for value in values:
            try: err = requirement(value, **kwargs)
            except TypeError: err = requirement(self._value) # old-style validator doesn't take **kwargs
            if err: return err
    return validate

def in_choices(choices):
    """
    Validates that the value of a ScalarInput is a valid choice,
    or that all values for the VectorInput are allowable choices.
    "choices" can be any of the formats taken by a ChoiceInput.
    """
    allowed = set()
    for choice in choices:
        if isinstance(choice, Choice): allowed.add(choice.value)
        elif isinstance(choice, (list,tuple)): allowed.add(choice[0])
        else: allowed.add(choice)
    def validate(values, **kwargs):
        ok = False
        # values is probably a list of values
        if is_scalar(values): ok = values in allowed
        else: ok = all(v in allowed for v in values)
        if not ok: return "Please select one of the permitted choices"
    return validate

def matches_peer(peername):
    '''Requires that two fields have identical values, e.g. for re-entering an email address.'''
    def validate(val, peers, **kwargs):
        peer = peers[peername]
        if not val: return # allow field to be empty, including the empty string
        if val != peer.value: return "Does not match %s" % peer.label
    return validate

### Display helpers for quickly generating HTML ###

def component_divs(component, div=u"div", css=u"edwa-"):
    """
    Returns three <div> elements enclosing the label, help message, and any errors, respectively.
    Any empty string may be returned in place of any of these if there is no content.
    The <div>s are assigned CSS classes of edwa-label, edwa-help, and edwa-error.
    You can change the "edwa-" to something else with the "css" parameter.
    """
    label_div, help_div, error_div = u"", u"", u""
    if component.label:
        label_div = u"<div class='%slabel'><label for='%s'>%s</label></div>" % (css, component.id, component.label)
    if component.help_text:
        help_div = u"<div class='%shelp'>%s</div>" % (css, component.help_text)
    if component.errors:
        err_lines = [u"<div class='%serror'>" % css]
        err_lines.append(u"<ul>")
        err_lines.extend(u"<li>%s</li>" % escape(err) for err in component.errors)
        err_lines.append(u"</ul>")
        err_lines.append(u"</div>")
        error_div = u"\n".join(err_lines)
    return (label_div, help_div, error_div)

def as_table(form, css=u"edwa-"):
    """
    Formats the form as a two-column table.
    No <form> or <table> tags are generated -- you must provide those!
    <tr> are given alternating styles edwa-row0 and edwa-row1.
    Help text + errors are wrapped in a <div> of class edwa-msgs,
    and the actual form control is wrapped in a edwa-input <div>.
    """
    lines = []
    row_idx = 0
    for component in form:
        if isinstance(component, HiddenInput):
            # These will create a small gap if placed between visisble components,
            # unless cellspacing=0 and cellpadding=0.
            lines.append(u"<tr><td colspan='2'>%s</td></tr>" % component.html())
            continue
        elif is_scalar(component):
            label, help, errors = component_divs(component, css=css)
            lines.append(u"<tr valign='top' class='%srow%s'><th align='right'>%s</th><td><div class='%sinput'>%s</div><div class='%smsgs'>%s%s</div></td></tr>" % (
                css, row_idx, label, css, component.html(), css, help, errors))
        else: # nested table for RadioSelect and CheckboxSelect
            lines.append(u"<tr valign='middle' class='%srow%s'><th align='right'>%s</th><td><div class='%schoices'><table border='0' cellspacing='0' cellpadding='0'>" % (
                css, row_idx, component.label, css))
            for child in component:
                label, help, errors = component_divs(child, css=css)
                lines.append(u"<tr valign='top' class='%srow%s'><td><div class='%sinput'>%s</div></td><td align='left'>%s</td><td><div class='%smsgs'>%s%s</div></td></tr>" % (
                    css, row_idx, css, child.html(), label, css, help, errors))
            label, help, errors = component_divs(component, css=css)
            lines.append(u"</table></div><div class='%smsgs'>%s%s</div></td></tr>" % (css, help, errors))
        row_idx = (row_idx + 1) % 2
    return u"\n".join(lines)

