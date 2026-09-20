"""
URL configuration for datefinder project.
"""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from calendar_app import dav

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('calendar/', include('calendar_app.urls')),
    path('.health', include('health.urls')),
    path('dav/calendar/', dav.dav_collection),
    path('dav/calendar/<str:uid>.ics', dav.dav_item),
    path('.well-known/caldav', RedirectView.as_view(url='/dav/calendar/', permanent=True)),
    path('', RedirectView.as_view(url='/calendar/', permanent=False)),
]
