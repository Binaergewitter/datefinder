from django.urls import path
from . import views

app_name = 'calendar_app'

urlpatterns = [
    path('', views.calendar_view, name='calendar'),
    path('confirm/', views.confirm_list_view, name='confirm'),
    path('api/toggle/<str:date>/', views.toggle_availability, name='toggle_availability'),
    path('api/availability/', views.get_all_availability, name='get_all_availability'),
    path('api/confirm/<str:date>/', views.confirm_date, name='confirm_date'),
    path('api/unconfirm/<str:date>/', views.unconfirm_date, name='unconfirm_date'),
    path('api/confirmed/', views.get_confirmed_dates, name='get_confirmed_dates'),
    path('api/next-podcast-number/', views.get_next_podcast_number, name='get_next_podcast_number'),
    path('export/calendar.ics', views.export_ical, name='export_ical'),
]
