from django.urls import path
from . import views

app_name = 'calendar_app'

urlpatterns = [
    path('', views.calendar_view, name='calendar'),
    path('api/toggle/<str:date>/', views.toggle_availability, name='toggle_availability'),
    path('api/availability/', views.get_all_availability, name='get_all_availability'),
]
