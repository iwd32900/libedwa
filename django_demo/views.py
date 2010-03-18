from django.http import HttpResponse, HttpResponseRedirect
from django.template import Template, Context
from django.conf import settings
#from django.shortcuts import render_to_response
#from django.core.urlresolvers import reverse
#from django import forms

import random
import libedwa

def controller(request, action_id=None):
    edwa_name = "_EDWA"
    edwa = request.session.get(edwa_name)
    if edwa:
        print "Recovering previously used EDWA object"
        edwa = libedwa.EDWA.loads(edwa)
    else:
        print "Creating new EDWA object"
        # States will not be bookmarkable / emailable b/c secret key is randomly generated and tied to session cookie.
        # Iff all sessions share the same secret key, then states can be shared with others.
        edwa = libedwa.EDWA("edwa_demo:controller:%i:%s" % (random.getrandbits(64), settings.SECRET_KEY), size_limit=100000)
    if action_id is None:
        page = edwa.start(request, MainPage.render, {'cnt':0})
    else:
        print "Action ID size is", len(action_id)
        page = edwa.run(request, action_id)
    request.session[edwa_name] = edwa.dumps()
    return page

class MainPage(object):
    def render(self, request, edwa):
        #return render_to_response('edwa_demo/test.html', vars())
        all_vars = dict(globals())
        all_vars.update(vars())
        return HttpResponse(Template(r"""<html><body>
{% eval edwa %}
<br>The counter is at {{ edwa.context.cnt }}.
<br><a href='{% eval edwa.make_action(self.add_one) %}'>add one &raquo;</a>
or <a href='{% url edwa_demo-controller %}'>reset &raquo;</a>
<p><a href='{% eval edwa.make_call(SecondPage.render) %}'>Get outta Dodge &raquo;</a>
</body></html>""").render(Context(all_vars)))
    def add_one(self, request, edwa):
        edwa.context.cnt += 1

class SecondPage(object):
    def render(self, request, edwa):
        all_vars = dict(globals())
        all_vars.update(vars())
        return HttpResponse(Template(r"""<html><body>
Page two!
<p>Use the back button or <a href='{% eval edwa.make_return() %}'>click here</a>.
</body></html>""").render(Context(all_vars)))
