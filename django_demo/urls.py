from django.conf.urls.defaults import *
from django_demo import views

urlpatterns = patterns('',
    # Example:
    url(r'^controller/$', views.controller, name='edwa_demo-controller'),
)
