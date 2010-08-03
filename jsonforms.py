"""
Advanced forms library allowing "nesting" one form inside another.
Uses JavaScript and JQuery (1.4+) to return results in JSON format.
"""
import uuid
try: import json
except ImportError: import simplejson as json

import libedwa.forms as ef

class NestedForm(ef.Form):
    """A hybrid of Form and VectorInput"""
    def __init__(self, name, **kwargs):
        self.name = self._name = name
        self.label = kwargs.pop("label", name.replace("_", " ").capitalize())
        self.extras = kwargs.pop("extras", {})
        self.errors = None
        self.require = kwargs.pop("require", [])
        if kwargs.pop("required", True): self.require = [ef.not_empty] + self.require
        super(NestedForm, self).__init__(**kwargs)
    def set_data(self, data=[], files=None):
        if files: raise ValueError("File uploads not supported!")
        data = data or [] # in case None is passed
        if isinstance(data, basestring): data = json.loads(data)
        elif ef.is_scalar(data): data = ef.as_vector(data)
        # Make sure keys are prefixed with the form-wide prefix.
        # Make sure values are lists -- convert bare values into single-item lists.
        self.data = [dict(((k if k.startswith(self.prefix) else self.prefix+k), ef.as_vector(v)) for k, v in datum.iteritems()) for datum in data]
    def rawvalues(self):
        return self._values_impl("rawvalues")
    def values(self):
        # If we've already computed our value, just return it.
        if hasattr(self, "_value"):
            return self._value
        # Enter validation mode. Start accumulating error messages.
        self.errors = []
        # Try to coerce the string form into a Python object.
        # Do not escape error messages here: they will be escaped before output.
        # This means they're still readable for e.g. console output.
        try:
            self._value = self._values_impl("values")
        except Exception, ex:
            self._value = []
            self.errors.append(unicode(ex))
        # If coerced successfully, apply the 'require' criteria (if any).
        for requirement in self.require:
            err = requirement(self._value)
            if err: self.errors.append(unicode(err))
        if self.errors: self._value = []
        return self._value
    def _values_impl(self, funcname):
        vals = []
        subforms = [child for child in self if isinstance(child, NestedForm)]
        all_data = self.data
        try:
            for datum in all_data:
                self.data = datum
                for child in subforms: child.set_data(datum.get(child.name))
                vals.append(getattr(super(NestedForm, self), funcname)())
        finally:
            self.data = all_data
        return vals
    def validate(self):
        self.value
        valid = not self.errors
        for child in self.children:
            valid = valid and child.validate()
        return valid
    @property
    def rawvalue(self):
        return self.rawvalues()
    @property
    def value(self):
        return self.values()

def make_template(nform, indent=""):
    """Returns as JavaScript object as a string, starting with "{" and ending with "}"."""
    lines = []
    j = json.dumps
    for child in nform:
        if isinstance(child, NestedForm):
            lines.append("%s%s: edwa.jsonforms.make%s(%s, %s, %s, %s)" % (
                indent, j(child.name), child.__class__.__name__, j(child.name), j(child.label), make_template(child, indent+"    "), j(child.extras)))
        else:
            lines.append("%s%s: edwa.jsonforms.make%s(%s, %s, %s)" % (
                indent, j(child.name), child.__class__.__name__, j(child.name), j(child.label), j(ef.format_attrs(child.attrs))))
    return "{\n" + ",\n".join(lines) + "\n" + indent + "}";

def make_html(nform, input_name="edwa-json"):
    """Makes a SCRIPT tag and the start of the FORM, still needs a submit button and a closing tag.
    JQuery and jsonforms.js should have already been included in the HEAD."""
    form_id = "%s%s_form" % (nform.id_prefix, nform.prefix)
    form_html = nform.html()
    template = make_template(nform, "    ")
    data = json.dumps(nform.rawvalues(), indent=4)
    return """<script type="text/javascript">
jQuery(document).ready(function() {
var template = %(template)s;

var data = %(data)s;

jQuery("#%(form_id)s").prepend(edwa.jsonforms.make_jsonform(data, template)).submit(function() {
    // JSON.stringify() can be obtained from the "json2" library if the browser does not provide it.
    jQuery("input[name=%(input_name)s]", this)[0].value = JSON.stringify(data);
});
});
</script>
%(form_html)s
<input type="hidden" name="%(input_name)s">
""" % vars()

def test_me():
    pet_form = NestedForm("pets")
    pet_form += ef.TextInput(pet_form, "name")
    pet_form += ef.TextInput(pet_form, "species")
    
    dep_form = NestedForm("dependents")
    dep_form += ef.TextInput(dep_form, "name")
    dep_form += ef.TextInput(dep_form, "age")
    dep_form += pet_form
    
    form = NestedForm("x")
    form += ef.TextInput(form, "name")
    form += ef.TextInput(form, "phone")
    form += dep_form
    
    data = {
        "name": "Juan Carlos Doe",
        "phone": "919-555-1234",
        "dependents": [
            { "name": "Maria", "age": "5" },
            { "name": "Ana", "age": "3" },
            { "name": "Juanita", "age": "1" },
            { "pets": [{}] } # an empty slot at the end of the list, with an empty slot for pets!
        ]
    }
    form.set_data(data)
    print "RAW", form.rawvalues()
    print "VAL", form.values()
    print "HTML", make_html(form)
