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
"""

from libedwa.html import escape, raw, format_attrs

def is_scalar(x):
    """False if x is a list-like iterable (list, tuple, etc.), but True if x is a string or other scalar."""
    if isinstance(x, basestring): return True
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
        self.set_data(data=data, files=files)
    def set_data(self, data={}, files={}):
        """
        data    A dictionary mapping HTML names (as strings) to lists of values.
                Bare, non-list values will automatically be wrapped in lists.
                This can either be initial values, or the result of form submission.
                Calling this function replaces any values passed previously or in the constructor,
                and overrides any values passed to individual inputs as initial=...
                In Django, try dict(request.POST.lists()).
        files   A dictionary mapping HTML names (as strings) to file-like objects.
                These will be wrapped in lists (like data) for consistency sake.
                In Django, try request.FILES.
        """
        if files:
            data = dict(data) # make a copy
            data.update(files) # include info about uploaded files
        # Make sure keys are prefixed with the form-wide prefix.
        # Make sure values are lists -- convert bare values into single-item lists.
        self.data = dict(((k if k.startswith(self.prefix) else self.prefix+k), as_vector(v)) for k, v in data.iteritems())
    def add(self, child):
        """Add a new input component to this form."""
        self.children.append(child)
        return self # needed to support "+=" syntax
    __iadd__ = add # so you can use "form += input_element"
    def __iter__(self):
        """Iterate over the components in this form."""
        return iter(self.children)
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
        errors = []
        for child in self.children:
            child.value
            errors += child.errors
            if not is_scalar(child):
                for grandchild in child:
                    grandchild.value
                    # these errors have already been included in the child
        return not errors
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
        require     a list of validation functions, which take one argument (the value)
                    and return either an error message (as a string) or None if the value is OK.
        initial     a fallback initial value if no data is provided to the Form
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
        if "initial" in kwargs: self._initial = kwargs.pop("initial")
        self.attrs = kwargs
        self.errors = None # list of error messages, if any, pre-escaped for HTML special chars
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
            self.errors.append(unicode(ex))
            return self._value
        # If coerced successfully, apply the 'require' criteria (if any).
        for requirement in self.require:
            err = requirement(self._value)
            if err: self.errors.append(unicode(err))
        if self.errors: self._value = None
        return self._value
    def objectify(self, value):
        """Convert the raw value into the standarized value, using self.type."""
        raise NotImplementedError()
    def html(self):
        """Render the component as an HTML string."""
        raise NotImplementedError()

class ScalarInput(Input):
    """Any form component that takes on at most one value."""
    @property
    def rawvalue(self):
        val = u""
        if self.name in self.form.data:
            val = self.form.data[self.name]
        elif hasattr(self, "_initial"):
            val = self._initial
        if not is_scalar(val): val = val[-1] # if multiple values, return the last one! (like Django)
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
        return u"<input type='password' id='%s' name='%s' value='%s'%s />" % (self.id, self.name, escape(self.rawvalue), format_attrs(self.attrs))

class HiddenInput(ScalarInput):
    def html(self):
        return u"<input type='hidden' id='%s' name='%s' value='%s'%s />" % (self.id, self.name, escape(self.rawvalue), format_attrs(self.attrs))

class FileInput(ScalarInput):
    """Provides either a file(-like) object, or None."""
    def __init__(self, form, name, **kwargs):
        kwargs["type"] = lambda x: x or None
        super(FileInput, self).__init__(form, name, **kwargs)
    def html(self):
        return u"<input type='file' id='%s' name='%s'%s />" % (self.id, self.name, format_attrs(self.attrs))

class BooleanInput(ScalarInput):
    """A control that returns False when unchecked, and a specified non-false value when checked."""
    def __init__(self, form, name, value=1, **kwargs):
        kwargs["type"] = bool
        super(BooleanInput, self).__init__(form, name, **kwargs)
        self.checked_value = value
    @property
    def rawvalue(self):
        """A little different from most inputs: rawvalue is True or False."""
        to_search = []
        if self.name in self.form.data:
            to_search = self.form.data[self.name]
        elif hasattr(self, "_initial"):
            to_search = as_vector(self._initial)
        strval = unicode(self.checked_value)
        val = any(strval == unicode(formval) for formval in to_search)
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
    @property
    def rawvalue(self):
        val = []
        if self.name in self.form.data:
            val = self.form.data[self.name]
        elif hasattr(self, "_initial"):
            val = as_vector(self._initial)
        if len(val) == 1 and getattr(self, "single_selection", False):
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
        self.choices = []
        for choice in kwargs.pop('choices', []):
            if isinstance(choice, Choice):
                self.choices.append(choice)
            elif isinstance(choice, (list,tuple)):
                self.choices.append(Choice(*choice))
            else:
                self.choices.append(Choice(choice))
        super(ChoiceInput, self).__init__(form, name, **kwargs)
        self.require.append(in_choices(self.choices))

class Select(ChoiceInput):
    """Defaults to single selection -- include multiple=True to allow multiple selection.
    Select.values is always a list, even when multiple=False."""
    def html(self):
        selected = set(escape(v) for v in self.rawvalue)
        lines = []
        lines.append(u"<select id='%s' name='%s'%s>" % (self.id, self.name, format_attrs(self.attrs)))
        for choice in self.choices:
            value, label = escape(choice.value), escape(choice.label)
            is_selected = (u" selected='selected'" if value in selected else u"")
            lines.append(u"<option value='%s'%s>%s</option>" % (value, is_selected, label))
        lines.append(u"</select>")
        return u"\n".join(lines)

class RadioSelect(ChoiceInput):
    """Although this derives from VectorInput, only one radio can be selected at a time.
    Thus, it returns a scalar value when a radio is selected.
    It returns the empty list when no radios are selected."""
    single_selection = True
    def __init__(self, form, name, **kwargs):
        super(RadioSelect, self).__init__(form, name, **kwargs)
        kwargs.pop("choices", None)
        kwargs.pop("label", None)
        self.children = [RadioInput(form, name, value=choice.value, label=choice.label, id_postfix=(".%i" % ii), **kwargs) for ii, choice in enumerate(self.choices)]
    def __iter__(self):
        for child in self.children: yield child

class CheckboxSelect(ChoiceInput):
    def __init__(self, form, name, **kwargs):
        super(CheckboxSelect, self).__init__(form, name, **kwargs)
        kwargs.pop("choices", None)
        kwargs.pop("label", None)
        self.children = [CheckboxInput(form, name, value=choice.value, label=choice.label, id_postfix=(".%i" % ii), **kwargs) for ii, choice in enumerate(self.choices)]
    def __iter__(self):
        for child in self.children: yield child

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

def DateTime(formats=DATE_TIME_FMTS):
    formats = as_vector(formats)
    def maketype(text):
        import datetime as dt
        for format in formats:
            try: return dt.datetime.strptime(text, format)
            except ValueError: pass
        raise ValueError("Cannot interpret '%s' as a date/time" % text)
    return maketype

def Date(formats=DATE_FMTS):
    f = DateTime(formats)
    def maketype(text):
        return f(text).date()
    return maketype

def Time(formats=TIME_FMTS):
    f = DateTime(formats)
    def maketype(text):
        return f(text).time()
    return maketype

### Validation functions to use with require=[...] ###
# Criteria to support: regex, slug, minlen/maxlen, email, url?

def not_empty(val):
    """A mandatory, non-empty form field."""
    if not val: return "Please enter a value"

def maximum(m):
    """Maximum numeric value, inclusive."""
    def validate(val):
        if val > m: return "Please enter a value of at most %s" % m
    return validate

def minimum(m):
    """Minimum numeric value, inclusive."""
    def validate(val):
        if val < m: return "Please enter a value of at least %s" % m
    return validate

def not_before(x):
    """Set limits on date and/or time. See as_date_or_time() for possible values of x."""
    dt = as_date_or_time(x)
    def validate(val):
        if val < dt: return "Please enter a date/time of %s or later" % x
    return validate

def not_after(x):
    """Set limits on date and/or time. See as_date_or_time() for possible values of x."""
    dt = as_date_or_time(x)
    def validate(val):
        if val > dt: return "Please enter a date/time of %s or earlier" % x
    return validate

def each(requirement):
    """Wrapper to turn validators that expect scalars into validators that expect lists."""
    def validate(values):
        for value in values:
            err = requirement(value)
            if err: return err
    return validate

def in_choices(choices):
    """Validates that all values for the VectorInput are allowable choices."""
    allowed = set(c.value for c in choices)
    def validate(values):
        ok = False
        # values is probably a list of values
        if is_scalar(values): ok = values in allowed
        else: ok = all(v in allowed for v in values)
        if not ok: return "Please select one of the permitted choices"
    return validate

### Display helpers for quickly generating HTML ###

def as_table(form, **kwargs):
    """
    table_attrs     dictionary of attributes (like 'class', 'cellspacing', etc.) for the TABLE tag
    error_class     CSS class(es) for the UL containing any errors
    label_class     CSS class(es) for the DIV containing the field label
    help_class      CSS class(es) for the DIV containing the help text
    """
    hiddens = []
    lines = [form.html(), u"<table%s>" % format_attrs(kwargs.get("table_attrs", {}))]
    def add_component(component):
        if component.errors:
            errmsg = u"<ul class='%s'>\n%s\n</ul>" % (kwargs.get("error_class", u""), u"\n".join(u"<li>%s</li>" % escape(err) for err in component.errors))
        elif component.help_text:
            errmsg = "<div class='%s'>%s</div>" % (kwargs.get("help_class", u""), component.help_text)
        else:
            errmsg = ""
        label = u"<div class='%s'><label for='%s'>%s</label></div>" % (kwargs.get("label_class", u""), component.id, component.label)
        #if component.help_text: label = "%s<div class='%s'>%s</div>" % (label, kwargs.get("help_class", u""), component.help_text)
        lines.append(u"<tr align='left' valign='middle'><td>%s</td><td>%s</td><td>%s</td></tr>" % (label, component.html(), errmsg))
    for component in form:
        if isinstance(component, HiddenInput):
            hiddens.append(component)
            continue
        if is_scalar(component):
            add_component(component)
        else:
            lines.append(u"<tr align='left' valign='middle'><td colspan='3'>%s:</td></tr>" % component.label)
            for child in component: add_component(child)
    lines.append(u"</table>")
    for component in hiddens:
        lines.append(component.html())
    lines.append(u"</form>")
    return u"\n".join(lines)

### Testing code, should eventually be (re)moved ###

def testit():
    form = Form(data={"first_name":"<John>", "gender":"other"}, prefix="pfx_")
    form += HiddenInput(form, "title", initial="Dr.")
    form += TextInput(form, "first_name", require=[not_empty])
    form += PasswordInput(form, "middle_name", require=[not_empty])
    form += TextInput(form, "last_name", initial='"Doe"', require=[not_empty])
    form += TextInput(form, "num_children", help_text="How many children?", type=int, require=[minimum(0), maximum(20)], initial="-1")
    form += Select(form, "gender", choices=("male", "female"))
    form += CheckboxInput(form, "spam_me", initial=True)
    form += CheckboxSelect(form, "hobbies", choices=((1, "sky-diving"), (2, "scuba diving"), (3, "knitting")), initial=["3"], type=int)
    print "Form is valid?", form.validate()
    print as_table(form, table_attrs={'width':'100%'})
    print form.rawvalues()
    print form.values()
    return form

