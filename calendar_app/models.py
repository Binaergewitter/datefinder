import secrets
import uuid

from django.contrib.auth.models import User
from django.db import models


def _generate_reminder_uid():
    return uuid.uuid4().hex


class ConfirmedDate(models.Model):
    """
    Model to store confirmed podcast dates.
    """
    date = models.DateField(unique=True)
    description = models.TextField(blank=True, default='')
    confirmed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='confirmed_dates'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"Confirmed: {self.date} - {self.description[:50]}"


class Reminder(models.Model):
    """
    Long-term reminder entries that appear in the shared iCal export.
    Any authenticated user can create, edit, or delete any reminder.
    """
    title = models.CharField(max_length=200)
    date = models.DateField()
    description = models.TextField(blank=True, default='')
    uid = models.CharField(max_length=64, unique=True, default=_generate_reminder_uid)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='reminders'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"Reminder: {self.date} - {self.title[:50]}"


class CalendarKey(models.Model):
    """
    Per-user CalDAV/JSON-API key, authenticates HTTP Basic as username + key.
    Stored plaintext so the settings page can always reveal it again.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='calendar_key')
    key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"CalendarKey: {self.user.username}"

    @classmethod
    def generate_for(cls, user):
        """Create or rotate the user's CalDAV key; returns the new key string."""
        key = secrets.token_hex(20)
        cls.objects.update_or_create(user=user, defaults={'key': key})
        return key


class Availability(models.Model):
    """
    Model to store user availability for specific dates.
    """
    AVAILABILITY_CHOICES = [
        ('available', 'Available'),
        ('tentative', 'Tentatively Available'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='availabilities')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=AVAILABILITY_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'Availabilities'
        unique_together = ['user', 'date']
        ordering = ['date']

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.status}"

    @classmethod
    def get_date_availability(cls, date):
        """
        Get all availability entries for a specific date.
        Returns a dict with user info and their status.
        """
        entries = cls.objects.filter(date=date).select_related('user')
        return [
            {
                'user_id': entry.user.id,
                'username': entry.user.get_full_name() or entry.user.username,
                'status': entry.status,
            }
            for entry in entries
        ]

    @classmethod
    def count_available(cls, date):
        """
        Count users available (including tentatively) for a date.
        """
        return cls.objects.filter(date=date).count()

    @classmethod
    def toggle_availability(cls, user, date):
        """
        Toggle user availability for a date.
        None -> Available -> Tentative -> None (deleted)
        Returns the new status or None if deleted.
        """
        try:
            entry = cls.objects.get(user=user, date=date)
            if entry.status == 'available':
                entry.status = 'tentative'
                entry.save()
                return 'tentative'
            else:
                entry.delete()
                return None
        except cls.DoesNotExist:
            entry = cls.objects.create(user=user, date=date, status='available')
            return 'available'
