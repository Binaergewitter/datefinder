import json
from datetime import date as date_type, timedelta
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Availability


@login_required
def calendar_view(request):
    """
    Main calendar view.
    """
    return render(request, 'calendar_app/calendar.html', {
        'user': request.user,
    })


@login_required
@require_POST
def toggle_availability(request, date):
    """
    Toggle the user's availability for a specific date.
    """
    date_str = date
    try:
        target_date = date_type.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)
    
    # Only allow toggling future dates
    if target_date < date_type.today():
        return JsonResponse({'error': 'Cannot modify past dates'}, status=400)
    
    # Toggle availability
    new_status = Availability.toggle_availability(request.user, target_date)
    
    # Get updated availability for this date
    date_availability = Availability.get_date_availability(target_date)
    available_count = len(date_availability)
    
    # Broadcast update to all connected clients via WebSocket
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "calendar_updates",
        {
            "type": "availability_update",
            "date": date_str,
            "availability": date_availability,
            "has_star": available_count >= 3,
        }
    )
    
    return JsonResponse({
        'success': True,
        'date': date_str,
        'user_status': new_status,
        'availability': date_availability,
        'has_star': available_count >= 3,
    })


@login_required
@require_GET
def get_all_availability(request):
    """
    Get all availability data for the current month and next few months.
    """
    today = date_type.today()
    # Get availability for the next 90 days
    end_date = today + timedelta(days=90)
    
    availabilities = Availability.objects.filter(
        date__gte=today,
        date__lte=end_date
    ).select_related('user')
    
    # Group by date
    by_date = {}
    for entry in availabilities:
        date_str = entry.date.isoformat()
        if date_str not in by_date:
            by_date[date_str] = []
        by_date[date_str].append({
            'user_id': entry.user.id,
            'username': entry.user.get_full_name() or entry.user.username,
            'status': entry.status,
        })
    
    # Add star info
    result = {}
    for date_str, entries in by_date.items():
        result[date_str] = {
            'availability': entries,
            'has_star': len(entries) >= 3,
        }
    
    return JsonResponse({
        'success': True,
        'current_user_id': request.user.id,
        'data': result,
    })
