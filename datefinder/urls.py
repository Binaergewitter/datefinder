"""
URL configuration for datefinder project.
"""

from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('calendar/', include('calendar_app.urls')),
    path('', RedirectView.as_view(url='/calendar/', permanent=False)),
]
