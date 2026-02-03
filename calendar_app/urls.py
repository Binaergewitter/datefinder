from django.urls import path
from . import views

app_name = 'calendar_app'

urlpatterns = [
    path('', views.calendar_view, name='calendar'),
    path('news/', views.news_view, name='news'),
    path('rss-notes/', views.rss_notes_view, name='rss_notes'),
    path('notes/', views.notes_view, name='notes'),
    path('confirm/', views.confirm_list_view, name='confirm'),
    path('api/rss/feeds/', views.get_rss_feeds, name='get_rss_feeds'),
    path('api/rss/add/', views.add_rss_feed, name='add_rss_feed'),
    path('api/rss/<int:feed_id>/delete/', views.delete_rss_feed, name='delete_rss_feed'),
    path('api/rss/<int:feed_id>/toggle/', views.toggle_rss_feed, name='toggle_rss_feed'),
    path('api/rss/news/', views.get_news, name='get_news'),
    path('api/notes/', views.get_notes, name='get_notes'),
    path('api/notes/add/', views.add_note, name='add_note'),
    path('api/notes/<int:note_id>/delete/', views.delete_note, name='delete_note'),
    path('api/toggle/<str:date>/', views.toggle_availability, name='toggle_availability'),
    path('api/availability/', views.get_all_availability, name='get_all_availability'),
    path('api/confirm/<str:date>/', views.confirm_date, name='confirm_date'),
    path('api/unconfirm/<str:date>/', views.unconfirm_date, name='unconfirm_date'),
    path('api/confirmed/', views.get_confirmed_dates, name='get_confirmed_dates'),
    path('api/next-podcast-number/', views.get_next_podcast_number, name='get_next_podcast_number'),
    path('export/calendar.ics', views.export_ical, name='export_ical'),
]
