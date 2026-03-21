from django.contrib import admin

from .models import Availability, Reminder


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'status', 'created_at', 'updated_at']
    list_filter = ['status', 'date', 'user']
    search_fields = ['user__username', 'user__email']
    date_hierarchy = 'date'


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ['title', 'date', 'description', 'created_by', 'created_at']
    list_filter = ['date']
    search_fields = ['title', 'description']
    date_hierarchy = 'date'
