"""
"""

from libedwa.html import escape, raw, format_attrs

class Form(object):
    """Basic HTML form.  To add fields, use "+=" rather than trying to subclass."""
    def __init__(self, action="", data={}, method="POST", prefix="", id_prefix="id_", **kwargs):
        """
        data    A dictionary mapping HTML names (as strings) to lists of values.
                Bare, non-list values will automatically be wrapped in lists.
                This can either be initial values, or the result of form submission.
                In Django, try request.POST.lists().
        """
        self.action = action
        # Make sure keys are prefixed with the form-wide prefix.
        # Make sure values are lists -- convert bare values into single-item lists.
        self.data = dict(((k if k.startswith(prefix) else prefix+k),
            (v if isinstance(v, list) else [v])) for k, v in data.iteritems())
        self.method = method
        self.prefix = prefix
        self.id_prefix = id_prefix
        self.attrs = kwargs
        self.children = []
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
    def is_valid(self):
        """
        Returns true iff all form components validate (i.e., have no errors).
        Calling is_valid() will cause error messages to be displayed with the form.
        """
        errors = []
        for child in self.children:
            child.value
            errors += child.errors
            try:
                for grandchild in child:
                    grandchild.value
                    # these errors have already been included in the child
            except TypeError: pass # most components are not iterable
        return not errors

### Various types of input objects to use in Forms ###

class Input(object):
    """Abstract base object for all form inputs."""
    def __init__(self, form, name, **kwargs):
        """
        form        the Form this input will belong to
        name        the value for the name="..." attribute
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
        self.id = form.id_prefix + self.name
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
        try:
            self._value = self.objectify(self.rawvalue)
        except Exception, ex:
            self._value = None
            self.errors.append(escape(ex))
            return self._value
        # If coerced successfully, apply the 'require' criteria (if any).
        for requirement in self.require:
            err = requirement(self._value)
            if err: self.errors.append(escape(err))
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
            if len(val): val = val[-1] # if multiple values, return the last one! (like Django)
        elif hasattr(self, "_initial"):
            val = self._initial
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
    pass # TODO: implement this

class BooleanInput(ScalarInput):
    def __init__(self, form, name, value=1, **kwargs):
        super(BooleanInput, self).__init__(form, name, **kwargs)
        self.checked_value = value
    @property
    def value(self):
        if super(BooleanInput, self).value:
            return self.checked_value
        else: return None
    def html(self):
        attrs = dict(self.attrs)
        attrs['checked'] = bool(self.rawvalue) # don't want to trigger validation
        return u"<input type='%s' id='%s' name='%s' value='%s'%s />" % (self.input_type, self.id, self.name, escape(self.checked_value), format_attrs(attrs))

class CheckboxInput(BooleanInput):
    input_type = "checkbox"

class RadioInput(BooleanInput):
    input_type = "radio"

class VectorInput(Input):
    @property
    def rawvalue(self):
        val = []
        if self.name in self.form.data:
            val = self.form.data[self.name]
        elif hasattr(self, "_initial"):
            val = self._initial
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

# TODO: this isn't really a multiple selection!
class RadioSelect(ChoiceInput):
    def __init__(self, form, name, **kwargs):
        super(RadioSelect, self).__init__(form, name, **kwargs)
        kwargs.pop("choices", None)
        self.children = [RadioInput(form, name, **kwargs) for choice in self.choices]
    def __iter__(self):
        for child in self.children: yield child

class CheckboxSelect(ChoiceInput):
    def __init__(self, form, name, **kwargs):
        super(CheckboxSelect, self).__init__(form, name, **kwargs)
        kwargs.pop("choices", None)
        kwargs.pop("label", None)
        self.children = [CheckboxInput(form, name, value=choice.value, label=choice.label, **kwargs) for choice in self.choices]
    def __iter__(self):
        for child in self.children: yield child

### Validation functions to use with require=[...] ###

def not_empty(val):
    """A mandatory, non-empty form field."""
    if not val: return "Please enter a value"

def maximum(m):
    """Maximum numeric value, inclusive."""
    def validate(val):
        if val > m: return "Please enter a value no larger than %s" % m
    return validate

def minimum(m):
    """Minimum numeric value, inclusive."""
    def validate(val):
        if val < m: return "Please enter a value no smaller than %s" % m
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
        try: ok = all(v in allowed for v in values)
        except:
            # But maybe it's a single value in some odd corner case...
            try: ok = values in allowed
            except: pass
        if not ok: return "Please select one of the permitted values"
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
        else:
            errmsg = ""
        # TODO: add <LABEL for=...> tag
        label = "<div class='%s'>%s</div>" % (kwargs.get("label_class", u""), component.label)
        if component.help_text: label = "%s<div class='%s'>%s</div>" % (label, kwargs.get("help_class", u""), component.help_text)
        lines.append("<tr align='left' valign='top'><td>%s</td><td>%s</td><td>%s</td></tr>" % (label, component.html(), errmsg))
    for component in form:
        if isinstance(component, HiddenInput):
            hiddens.append(component)
            continue
        try:
            children = iter(component)
            # TODO: add header line for "wrapper" component
            for child in children: add_component(child)
        except TypeError: # simple component, not iterable
            add_component(component)
    lines.append("</table>")
    for component in hiddens:
        lines.append(component.html())
    lines.append("</form>")
    return u"\n".join(lines)

def testit():
    form = Form(data={"first_name":"<John>", "gender":"other"}, prefix="pfx_")
    form += HiddenInput(form, "title", initial="Dr.")
    form += TextInput(form, "first_name", require=[not_empty])
    form += PasswordInput(form, "middle_name", require=[not_empty])
    form += TextInput(form, "last_name", initial='"Doe"', require=[not_empty])
    form += TextInput(form, "num_children", help_text="How many children?", type=int, require=[minimum(0), maximum(20)], initial="-1")
    form += Select(form, "gender", choices=("male", "female"))
    form += CheckboxInput(form, "spam_me", initial=True)
    # TODO: CheckboxSelect and RadioSelect don't work properly yet!
    form += CheckboxSelect(form, "hobbies", choices=((1, "sky-diving"), (2, "scuba diving"), (3, "knitting")))
    print "Form is valid?", form.is_valid()
    print as_table(form, table_attrs={'width':'100%'})

