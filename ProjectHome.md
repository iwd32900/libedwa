# Summary #

LibEDWA implements the [Front Controller pattern](http://en.wikipedia.org/wiki/Front_Controller_pattern) plus "stateless" session data to make complex flow control in Python web apps easy. LibEDWA is NOT another web framework -- its a little library that works with the framework you already have to make development easier.

# Why? #

As a solo developer, I needed to bridge the gap between simple server-side web pages (ala PHP) and a full-blown JavaScript application running in a browser (ala Gmail).  Simple web pages are pretty limiting for anything more complicated than some database CRUD: most frameworks leave you to re-invent navigation/flow control on your own.  Full-blown JavaScript applications are powerful, but painful and labor-intensive to develop (in my experience).  LibEDWA tries to combine the relative simplicity of server-side development (HTML + CSS + forms) with a more traditional "application" structure (e.g. links invoke callbacks on the server side, instead of just GETting URLs).  This code is a re-imagination of some PHP code (yuck!) that's worked well for me in developing scientific web apps.  I'd be interested in hearing about any other domains where this development model works particularly well.

# Key features #

  1. **The back button works as Undo.** Most apps store session data in cookies, where it's overwritten on each request.  With LibEDWA, data is stored in URLs and/or form fields, so previous application states are retained in the browser history.  For instance, you could remove items from your LibEDWA shopping cart just by using the back button. (Where appropriate, LibEDWA can be freely mixed and matched with cookie-based storage.)
  1. **GOTO considered harmful.** Normal web development only understands "GOTOs" (links) between pages, but LibEDWA allows one page to "call" another, and for that to "return" when finished.  Add an item to your shopping cart, then return to the item page.  Change your account settings, then go back to where you started from.  No bookkeeping required.
  1. **Client-side actions trigger server-side callbacks.** Clicking a link or submitting a form triggers a callback in the web application, much like clicking a button in a desktop GUI app triggers a callback. The event-handling logic (which _changes_ the application state) and the page-display logic (which _visualizes_ the application state) are cleanly separated.
  1. **Secure by default.** All client-side data is cryptographically signed (and optionally encrypted with [Keyczar](http://www.keyczar.org/)).  Since "location" in the app is determined by session data, not URL, access control is simplified.
  1. **No database required.** All data can be securely encoded into URLs and hidden form fields, so no persistent storage is necessary on the server side.  Application states can be bookmarked or even transferred by email (depending on configuration).  However, a database backend is also provided, to reduce bandwidth usage when a lot of data is being stored.
  1. **Small and light.** About 200 lines of Python for the core, and another 100 for the Keyczar-encrypted and database backends.
  1. **Works with Django out of the box.** A [toy Django/LibEDWA application](https://code.google.com/p/libedwa/source/browse/django_demo/views.py) is provided to demonstrate usage, but LibEDWA should be easy to use with any Python web framework.

# What it looks like #
```
class MainPage(object):
    def render(self, request, edwa):
        all_vars = dict(globals())
        all_vars.update(vars())
        return HttpResponse(Template(r"""<html><body>
<br>The counter is at {{ edwa.context.cnt }}.
<br><a href='{% eval edwa.href_action(self.add_one) %}'>add one &raquo;</a>
or <a href='{% url edwa_demo-controller %}'>reset &raquo;</a>
<p><a href='{% eval edwa.href_call(SubPage.render, return_handler=self.on_return) %}'>Do a "call" to SubPage &raquo;</a>
{{ edwa.hidden_form|safe }}
</body></html>""").render(Context(all_vars)))
    def add_one(self, request, edwa):
        edwa.context.cnt += 1
    def on_return(self, edwa, return_value, return_context):
        if return_value is not None:
            edwa.context["cnt"] += return_value
```
See the [full Django toy application](https://code.google.com/p/libedwa/source/browse/django_demo/views.py) comments and documentation!

# Getting started #
```
easy_install Django==1.1.1
hg clone https://libedwa.googlecode.com/hg/ libedwa
libedwa/django_demo/manage.py syncdb
libedwa/django_demo/manage.py runserver
open http://127.0.0.1:8000/controller/
```