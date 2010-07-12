################################################################################
#
# This is a toy Django application to demonstrate use of LibEDWA.
# In a *real* application, we would use templates in files, etc.
# To make it easy to follow, however, we're inlining templates here.
#
# The main page has a counter with a link we can use to increment it by one.
# There's also a "sub page" we can call to increment by a user-specified value.
#
################################################################################
from django.http import HttpResponse, HttpResponseRedirect
from django.template import Template, Context
from django.conf import settings
import django.forms

import random, uuid
import libedwa
from libedwa import html, forms

# Install the {% eval %} and {% exec %} tags without needing to {% load %} them.
# These will now be available to all Templates by default!
import libedwa.django_eval

# If you have SQL Alchemy installed, LibEDWA can store data server-side in a database.
USE_DB = False
if USE_DB:
    import sqlalchemy
    sa_engine = sqlalchemy.create_engine("sqlite://")



# This is the main entry point for the application.  All requests come through this URL.
def controller(request):
    if USE_DB: key_name = "_EDWA_controller_DB"
    else: key_name = "_EDWA_controller_GET"
    if key_name not in request.session:
        # For greater security, each session (identified by cookie) has its own secret key.
        # If all sessions shared the same secret key and we use_GET, then states could be bookmarked / emailed.
        if USE_DB: request.session[key_name] = uuid.uuid4().hex
        else: request.session[key_name] = "edwa_demo:controller:%i:%s" % (random.getrandbits(64), settings.SECRET_KEY)
    # Create the EDWA object to encode / decode page state and event handlers.
    if USE_DB: edwa = libedwa.DatabaseEDWA(sa_engine, request.session[key_name])
    else: edwa = libedwa.EDWA(request.session[key_name], use_GET=True)
    # Pulling from REQUEST means we can configure EDWA to use either GET or POST.
    # This is important, because even if configured to use GET, really large
    # requests automatically failover to POST mode (to work around browser limits).
    action_id = request.REQUEST.get(edwa.ACTION_KEY)
    page_id = request.REQUEST.get(edwa.PAGE_KEY)
    if action_id is None:
        # This is what happens on the first request, when a new user arrives.
        return edwa.start(request, MainPage.render, {'cnt':0})
    else:
        # This is what happens on every subsequent request.
        return edwa.run(request, action_id, page_id)



# By convention, we use classes to define mini-namespaces
# for a view function and its associated event handlers.
# These functions could live at the module level if you prefer, though.
# Classes are *only* used as namespaces: instance data is not preserved.
class MainPage(object):
    # This function is called to *display* the current application state.
    # It cannot *change* the application state (edwa.context), however.
    def render(self, request, edwa):
        # For simplicity, I make all symbols visible inside the template.
        # We need globals too, so that we can see the other page classes.
        all_vars = dict(globals())
        all_vars.update(vars())
        # Note that href_action() is just a shortcut for href(make_action()).
        # make_XXX() generates the actual encoded data, and href() wraps it
        # in a format that can be used in a URL.
        #
        # If you don't want your designers to {% eval ... %} code in your templates,
        # you'll have to generate the URLs for them ahead of time in your view function.
        return HttpResponse(Template(r"""<html><body>
<br>The counter is at {{ edwa.context.cnt }}.
<br><a href='{% eval edwa.href_action(self.add_one) %}'>add one &raquo;</a>
or <a href='{% url edwa_demo-controller %}'>reset &raquo;</a>
<p><a href='{% eval edwa.href_call(SubPage.render, return_handler=self.on_return) %}'>Do a "call" to SubPage &raquo;</a><p>
<p><a href='{% eval edwa.href_goto(FormPage.render) %}'>Try the EDWA HTML and forms libraries &raquo;</a><p>
{{ edwa.hidden_form|safe }}
</body></html>""").render(Context(all_vars)))
    # This is an event handler, triggered by a click on the "add one" link.
    # It is allowed to change the application state by writing to edwa.context.
    # Since it doesn't call do_goto(), do_call(), etc.,
    # the same page (MainPage.render) will be displayed after it finishes.
    def add_one(self, request, edwa):
        # The context can be accessed using dot notation...
        edwa.context.cnt += 1
    # This is a return handler, triggered when we "return" from SubPage
    # by successfully submitting the form.
    # That form value is passed here, to be added to the counter.
    def on_return(self, edwa, return_value, return_context):
        # SubPage has a link that returns without providing a return value,
        # so we have to check for that here:
        if return_value is not None:
            # ... or the context can be accessed using dictionary notation.
            edwa.context["cnt"] += return_value



class SubPage(object):
    class Form(django.forms.Form):
        amount = django.forms.IntegerField(label="Amount to add to counter", min_value=1, max_value=10)
    def render(self, request, edwa):
        # If POST_KEY is present in the form data, this POST resulted
        # from clicking a hyperlink that submitted the hidden LibEDWA form.
        # We should ignore it -- our "user" form wasn't submitted.
        if request.method == "POST" and edwa.POST_KEY not in request.POST:
            # Bound data will only be used for displaying errors
            # when form validation failed.
            # If form was valid, on_submit() would have already re-directed!
            myform = self.Form(request.POST)
        else:
            myform = self.Form()
        all_vars = dict(globals())
        all_vars.update(vars())
        # We need to use {% raweval %} here to keep Django from escaping the HTML!
        # form_action() generates the hidden form INPUTs needed to process the event.
        return HttpResponse(Template(r"""<html><body>
<form action='' method='POST'>
{{ myform.as_p }}
{% raweval edwa.form_action(self.on_submit) %}
<input type='Submit'>
</form>
<p>Use the back button or <a href='{% eval edwa.href_return() %}'>click here</a> to return without adding anything.
{{ edwa.hidden_form|safe }}
</body></html>""").render(Context(all_vars)))
    # Event handler triggered by form submission:
    def on_submit(self, request, edwa):
        myform = self.Form(request.POST)
        if myform.is_valid():
            # The return handler set up by MainPage is called instantly,
            # but the new page is not displayed until this handler returns.
            edwa.do_return(myform.cleaned_data['amount'])



class FormPage(object):
    def render(self, request, edwa):
        form = forms.Form(data={"first_name":"<John>", "gender":"other"}, prefix="pfx_")
        form += forms.HiddenInput(form, "title", initial="Dr.")
        form += forms.TextInput(form, "first_name", require=[forms.not_empty])
        form += forms.PasswordInput(form, "middle_name", require=[forms.not_empty])
        form += forms.TextInput(form, "last_name", initial='"Doe"', require=[forms.not_empty])
        form += forms.TextInput(form, "num_children", help_text="How many children?", type=int, require=[forms.minimum(0), forms.maximum(20)], initial="-1")
        form += forms.Select(form, "gender", choices=("male", "female"))
        form += forms.CheckboxInput(form, "spam_me", initial=True)
        form += forms.CheckboxSelect(form, "hobbies", choices=((1, "sky-diving"), (2, "scuba diving"), (3, "knitting")), initial=["3"], type=int)
        form += forms.Button(form, "Validate")
        if request.method == "POST":
            form.set_data(dict(request.POST.lists()))
            form.validate() # trigger validation and error display
        response = HttpResponse()
        t = html.Tagger(response, indent=2)
        with t.html.body:
            t(html.raw(forms.as_table(form)))
            t.hr("")
            t.p(form.validate())
            t.p(form.rawvalues())
            t.p(form.values())
        return response
