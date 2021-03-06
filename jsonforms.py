"""
Advanced forms library allowing "nesting" one form inside another.
Uses JavaScript and JQuery (1.4+) to return results in JSON format.
"""
from builtins import zip
from past.builtins import basestring
import uuid
from copy import deepcopy
from copy import copy as shallow_copy
try: import json
except ImportError: import simplejson as json

from libedwa.forms import *

class NestedForm(Form):
    """A hybrid of Form and VectorInput"""
    def __init__(self, name, **kwargs):
        self.name = self._name = name
        self.label = kwargs.pop("label", name.replace("_", " ").capitalize())
        self.errors = None
        self.require = kwargs.pop("require", [])
        self._valid = False
        self.kids = None # a list of deep copies of self.children
        if kwargs.pop("required", True): self.require = [not_empty] + self.require
        super(NestedForm, self).__init__(**kwargs)
    def set_data(self, data=[], files=None):
        """
        data    A dictionary mapping HTML names (as strings) to lists of values,
                or a list of such dictionaries, or such a list as a JSON string.
                Bare, non-list values will automatically be wrapped in lists.
                This can either be initial values, or the result of form submission.
                Calling this function replaces any values passed previously or in the constructor,
                and overrides any values passed to individual inputs as initial=...
                In Django, try request.POST['edwa-json']
                In Bottle, try request.forms['edwa-json']
        files   For compatibility with libedwa.Form only.  Do not use.
        
        This can only be called on the top-level nested form.
        Trying to use it directly on nested (child) forms will have no effect,
        because of the way data is propagated to child forms.
        """
        if files: raise ValueError("File uploads not supported!")
        if data is None: data = []
        elif isinstance(data, basestring): data = json.loads(data)
        elif is_scalar(data): data = as_vector(data)
        # Make sure keys are prefixed with the form-wide prefix.
        # Make sure values are lists -- convert bare values into single-item lists.
        self.data = [dict(((k if k.startswith(self.prefix) else self.prefix+k), as_vector(v)) for k, v in datum.items()) for datum in data]
        # Need to re-initialize the subforms
        self.kids = None
    def rawvalues(self):
        return self._values_impl("rawvalues")
    def jsonvalues(self):
        # Errors will only be present if values() or validate() was called.
        return self._values_impl("jsonvalues")
    def values(self):
        # If we've already computed our value, just return it.
        if hasattr(self, "_value"):
            return self._value
        # Enter validation mode. Start accumulating error messages.
        self.errors = []
        self._valid = True
        # Do not escape error messages here: they will be escaped before output.
        # This means they're still readable for e.g. console output.
        try:
            self._value = self._values_impl("values")
        except Exception as ex:
            self._value = []
            self.errors.append(to_unicode(ex))
        # If coerced successfully, apply the 'require' criteria (if any).
        for requirement in self.require:
            try: err = requirement(self._value) # add kwargs here as needed!
            except TypeError: err = requirement(self._value) # old-style validator doesn't take **kwargs
            if err: self.errors.append(to_unicode(err))
        if self.errors:
            self._value = []
            self._valid = False
        return self._value
    def _values_impl(self, mode):
        if self.kids is None:
            # Break references between children and self to reduce scope of deep copying:
            old_forms = [(child, getattr(child, "form", None)) for child in self.children]
            for child in self.children:
                if hasattr(child, "form"): child.form = None
            # Make a deep copy of self.children for each set of data we have:
            self.kids = []
            for datum in self.data:
                #new_kids = deepcopy(self.children)
                new_kids = [shallow_copy(child) for child in self.children]
                for kid in new_kids:
                    # Otherwise, kid.form points to a new, copied form object:
                    if hasattr(kid, "form"): kid.form = self
                    # This is used by the validation machinery for inter-Input dependencies:
                    kid.peers = new_kids # since kid.form.children refers to the unused, prototypical NestedForm.children
                    # This is the proper time to set data, so it isn't re-set unnecessarily.
                    if isinstance(kid, NestedForm): kid.set_data(datum.get(kid._name))
                self.kids.append(new_kids)
            # Restore links between (prototypical) children and self:
            for child, old_form in old_forms:
                if hasattr(child, "form"): child.form = old_form
        vals = []
        all_data = self.data
        try:
            # Define mode of data retrieval and error handling / validation
            if mode == "rawvalues":
                def prop(child): return child.rawvalue
            elif mode == "jsonvalues":
                def prop(child):
                    p = (child.jsonvalues() if hasattr(child, "jsonvalues") else child.rawvalue)
                    if child.errors and not isinstance(child, NestedForm): p = {"value":p, "errors":child.errors}
                    return p
            elif mode == "values":
                def prop(child):
                    self._valid &= child.validate()
                    return child.value
            else: assert False, "Unknown mode of operation!"
            # Cycle through each dataset in the array and process it.
            # Each dataset is processed with a clean copy of the child fields.
            for datum, children in zip(all_data, self.kids):
                self.data = datum
                vals.append(dict((child._name, prop(child)) for child in children))
        finally:
            self.data = all_data
        if mode == "jsonvalues" and self.errors:
            vals = {"value":vals, "errors":self.errors}
        return vals
    def validate(self):
        self.value
        return self._valid
    @property
    def rawvalue(self):
        return self.rawvalues()
    @property
    def value(self):
        return list(self.values())

def make_template(nform, extras, indent=""):
    """Returns as JavaScript object as a string, starting with "{" and ending with "}"."""
    lines = []
    j = json.dumps
    for child in nform:
        if isinstance(child, NestedForm):
            lines.append("%s%s: edwa.jsonforms.make%s(%s, %s, %s, %s)" % (
                indent, j(child._name), child.__class__.__name__, j(child._name), j(child.label), make_template(child, extras, indent+"    "), j(extras)))
        else:
            lines.append("%s%s: edwa.jsonforms.make_input(%s, %s, %s, %s)" % (
                indent, j(child._name), j(child._name), j(child.label), j(child.help_text or ""), j(child.html())))
    return "{\n" + ",\n".join(lines) + "\n" + indent + "}";

def make_html(nform, extras={}, input_name="edwa-json"):
    """Makes a SCRIPT tag and the start of the FORM, still needs a submit button and a closing tag.
    JQuery and jsonforms.js should have already been included in the HEAD."""
    form_id = "%s%s_form" % (nform.id_prefix, nform.prefix)
    form_html = nform.html()
    template = make_template(nform, extras, "    ")
    data = json.dumps(nform.jsonvalues(), indent=4)
    return """<script type="text/javascript">
jQuery(document).ready(function() {
var template = %(template)s;

var data = %(data)s;

jQuery("#%(form_id)s").prepend(edwa.jsonforms.make_jsonform(data, template)).submit(function() {
    // Programatic changes (this.value = ...) to input elements do not generate change events.
    // Thus, for safety, we trigger one manually before submit.  :input matches textareas, selects, checkboxes, etc.
    jQuery(":input").change();
    // JSON.stringify() can be obtained from the "json2" library if the browser does not provide it.
    jQuery("input[name=%(input_name)s]", this)[0].value = JSON.stringify(data);
});
});
</script>
%(form_html)s
<input type="hidden" name="%(input_name)s">
""" % vars()

def path_to_jsonforms_js():
    import os.path as p
    return p.abspath(p.join(p.dirname(__file__), "jsonforms.js"))

def test_me():
    pet_form = NestedForm("pets", required=False)
    pet_form += TextInput(pet_form, "name")
    pet_form += Select(pet_form, "species", choices=("perro", "gato", "pez", ("hamster", raw("h&aacute;mster"))))#, multiple=True)
    
    dep_form = NestedForm("dependents")
    dep_form += TextInput(dep_form, "name")
    dep_form += TextInput(dep_form, "age")
    dep_form += pet_form
    
    form = NestedForm("x")
    form += TextInput(form, "name")
    form += TextInput(form, "phone")
    form += CheckboxInput(form, "call_me")
    form += dep_form
    
    data = {
        "name": "Juan Carlos Doe",
        "phone": "",#919-555-1234",
        "call_me": True,
        "dependents": [
            { "name": "Maria", "age": "5" },
            { "name": "Ana", "age": "3" },
            { "name": "Juanita", "age": "1" },
            { "pets": [{"species": "pez"}] } # an empty slot at the end of the list, with an empty slot for pets!
        ]
    }
    form.set_data(data)
    #print "RAW", form.rawvalues()
    #print "VAL", form.values()
    #print "HTML", make_html(form)
    return form
