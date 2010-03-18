"""A very simple module to make Django templates suck less,
by allowing you to embed real Python expressions in the directly.
To use it, just import it from your settings.py file,
and the tags will be added to Django's default set.

The "exec" tag is the most flexible, in that it allows you to assign results to a variable,
and then use that variable like anything else that was passed into the template context:

  {% exec mytest = foo > bar %}
  {% if mytest %}
    Test result was {{ mytest }}.
  {% endif %}

The "eval" tag allows you to embed an expression directly for display,
allowing you to bypass the temporary variable in many cases:

  Test result was {% eval foo > bar %}.

Unfortunately, real Python control structures require newlines,
and embedding newlines inside tags doesn't seem to work.
You can still use the "foo if bar else baz" syntax, though,
and if you need something more complicated, maybe you shouldn't be doing it in a template?
"""
from django import template
from django.utils.html import conditional_escape
register = template.Library()

class EvalNode(template.Node):
    def __init__(self, code, raw=False):
        super(EvalNode, self).__init__()
        tagname, self.code = code.contents.split(None, 1)
        self.raw = raw
    def render(self, context):
        val = eval(self.code, {}, context)
        if context.autoescape and not self.raw: val = conditional_escape(val)
        return val
@register.tag(name="eval")
def do_eval(parser, token):
    """Allows you to embed Python expressions in a template: {% eval float(1 + 2) %}"""
    return EvalNode(token)
@register.tag(name="raweval")
def do_raweval(parser, token):
    """Like {% eval %}, but the string representation is rendered without HTML escaping."""
    return EvalNode(token, raw=True)

class ExecNode(template.Node):
    def __init__(self, code):
        super(ExecNode, self).__init__()
        tagname, self.code = code.contents.split(None, 1)
    def render(self, context):
        exec self.code in {}, context
        return ''
@register.tag(name="exec")
def do_exec(parser, token):
    """Allows you to embed Python statements in a template: {% exec newvar = 1 + 2 %} ... {{ newvar }}"""
    return ExecNode(token)

# Make these new tags globally available to all Django templates by default.
template.add_to_builtins('edwa.django_eval')
