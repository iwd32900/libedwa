from libedwa import *

class ExerciseApi(object):
    """Simple demonstration of the API, without real HTTP requests."""
    def run3(self):
        self.run(DatabaseEDWA, "sqlite:////home/ian.davis/tmp-edwa.db", None)
    def run2(self):
        self.run(KeyczarEDWA, "/home/ian.davis/tmp-pycrypto/crypt_keys")
    def run1(self):
        self.run(EDWA, 'my-secret-key')
    def run(self, EdwaClass, *args):
        def show(action_id):
            print("    Action ID length:", len(action_id))
            return action_id
        edwa = EdwaClass(*args)
        edwa.start("<FAKE_REQUEST>", self.page1)
        edwa.run("<FAKE_REQUEST>", show(edwa.make_noop()), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action3)), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_call(self.page2, return_handler=self.onreturn1)), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action1)), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_goto(self.page3)), edwa.make_page_data())
        for i in range(100): edwa.make_goto(self.page4)
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action1)), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action2)), edwa.make_page_data()) # this does a call()
        edwa.run("<FAKE_REQUEST>", show(edwa.make_return()), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_return("HIMOM!")), edwa.make_page_data())
        edwa.run("<FAKE_REQUEST>", show(edwa.make_action(self.action1)), edwa.make_page_data())
        print("Suspending...")
        action_id = edwa.make_noop() # save current state
        page_data = edwa.make_page_data()
        print("Re-animating...")
        edwa = EdwaClass(*args) # clean object
        edwa.run("<FAKE_REQUEST>", action_id, page_data) # restore state (current view, etc)
        ## This makes encoding expensive (~ 1 sec), b/c it adds 100 large Action objects to be interned.
        for i in range(100): edwa.make_goto(self.page4)
        return edwa
    def page1(self, request, edwa):
        print("On page 1.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
    def page2(self, request, edwa):
        print("On page 2.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
    def page3(self, request, edwa):
        print("On page 3.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
    def page4(self, request, edwa):
        print("On page 4.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
    def action1(self, request, edwa):
        print("  Entering action 1.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
        edwa.context['foo'] = 'bar'
        edwa.context['big'] = list(range(10000))
        print("  Exiting action 1.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
    def action2(self, request, edwa):
        print("  Entering action 2.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
        edwa.do_call(self.page4, {"fizz":"buzz"}, self.onreturn1, "EXTRA-STUFF")
        print("  Exiting action 2.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
    def action3(self, request, edwa):
        print("  Entering action 3.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
        edwa.context['name'] = 'John Q. Public'
        edwa.context['address'] = '123 Main St, Ste 456'
        edwa.context['city'] = 'Couldabeenanywhere'
        edwa.context['state'] = 'Alaska'
        edwa.context['zip'] = '12345-6789'
        edwa.context['phone_home'] = '555-987-6543'
        print("  Exiting action 3.  Request=%s.  Context=%s." % (request, edwa.context.keys()))
    def onreturn1(self, edwa, return_value, return_context):
        print("Return value %s in context %s" % (return_value, return_context))
