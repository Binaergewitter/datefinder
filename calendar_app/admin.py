from django.contrib import admin
from .models import Availability


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ['user', 'date', 'status', 'created_at', 'updated_at']
    list_filter = ['status', 'date', 'user']
    search_fields = ['user__username', 'user__email']
    date_hierarchy = 'date'
