from django.db import models
from django.contrib.auth.models import User


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
