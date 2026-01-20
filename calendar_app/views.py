import json
import logging
import urllib.request
import urllib.error
from datetime import date as date_type, datetime, timedelta
import uuid
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Availability, ConfirmedDate
from .hooks import run_confirm_hooks, run_unconfirm_hooks

logger = logging.getLogger(__name__)


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


@login_required
def confirm_list_view(request):
    """
    View showing future dates with 2+ availabilities for confirmation.
    """
    today = date_type.today()
    
    # Get dates with 2+ availabilities
    dates_with_availability = (
        Availability.objects.filter(date__gte=today)
        .values('date')
        .annotate(count=Count('id'))
        .filter(count__gte=1) # at least one confirmation
        .order_by('date')
    )
    
    # Get confirmed dates
    confirmed_dates = set(
        ConfirmedDate.objects.filter(date__gte=today)
        .values_list('date', flat=True)
    )
    
    # Build result with availability details
    candidate_dates = []
    for item in dates_with_availability:
        d = item['date']
        availability = Availability.get_date_availability(d)
        is_confirmed = d in confirmed_dates
        confirmed_info = None
        if is_confirmed:
            confirmed_obj = ConfirmedDate.objects.get(date=d)
            confirmed_info = {
                'description': confirmed_obj.description,
                'confirmed_by': confirmed_obj.confirmed_by.get_full_name() or confirmed_obj.confirmed_by.username if confirmed_obj.confirmed_by else 'Unknown',
            }
        candidate_dates.append({
            'date': d.isoformat(),
            'date_display': d.strftime('%A, %B %d, %Y'),
            'count': item['count'],
            'availability': availability,
            'is_confirmed': is_confirmed,
            'confirmed_info': confirmed_info,
        })
    
    return render(request, 'calendar_app/confirm.html', {
        'user': request.user,
        'candidate_dates': candidate_dates,
    })


@login_required
@require_POST
def confirm_date(request, date):
    """
    Confirm a date as the next podcasting date.
    """
    date_str = date
    try:
        target_date = date_type.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)
    
    # Only allow confirming future dates
    if target_date < date_type.today():
        return JsonResponse({'error': 'Cannot confirm past dates'}, status=400)
    
    # Check if date has 2+ availabilities
    availability_count = Availability.count_available(target_date)
    if availability_count < 2:
        return JsonResponse({'error': 'Date must have at least 2 available users'}, status=400)
    
    # Get description from request body
    try:
        body = json.loads(request.body)
        description = body.get('description', '')
    except json.JSONDecodeError:
        description = ''
    
    # Create or update confirmed date
    confirmed, created = ConfirmedDate.objects.update_or_create(
        date=target_date,
        defaults={
            'description': description,
            'confirmed_by': request.user,
        }
    )
    
    logger.debug(f"Date {'created' if created else 'updated'} in database: {target_date}")
    
    # Broadcast update to all connected clients via WebSocket
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "calendar_updates",
        {
            "type": "confirmation_update",
            "date": date_str,
            "confirmed": True,
            "description": description,
            "confirmed_by": request.user.get_full_name() or request.user.username,
        }
    )
    
    logger.debug(f"WebSocket broadcast sent for date: {date_str}")
    
    # Run post-action hooks
    logger.info(f"Running confirm hooks for date {target_date} with description: {description}")
    run_confirm_hooks(target_date, description, request.user)
    logger.debug(f"Confirm hooks completed for date: {target_date}")
    
    return JsonResponse({
        'success': True,
        'date': date_str,
        'confirmed': True,
        'description': description,
    })


@login_required
@require_POST
def unconfirm_date(request, date):
    """
    Remove confirmation from a date.
    """
    date_str = date
    try:
        target_date = date_type.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)
    
    # Delete confirmed date if exists
    deleted, _ = ConfirmedDate.objects.filter(date=target_date).delete()
    
    if deleted:
        # Broadcast update to all connected clients via WebSocket
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "calendar_updates",
            {
                "type": "confirmation_update",
                "date": date_str,
                "confirmed": False,
                "description": "",
                "confirmed_by": "",
            }
        )
        
        # Run post-action hooks
        run_unconfirm_hooks(target_date)
    
    return JsonResponse({
        'success': True,
        'date': date_str,
        'confirmed': False,
    })


@login_required
@require_GET
def get_confirmed_dates(request):
    """
    Get all confirmed dates.
    """
    today = date_type.today()
    confirmed = ConfirmedDate.objects.filter(date__gte=today).select_related('confirmed_by')
    
    result = {}
    for entry in confirmed:
        result[entry.date.isoformat()] = {
            'description': entry.description,
            'confirmed_by': entry.confirmed_by.get_full_name() or entry.confirmed_by.username if entry.confirmed_by else 'Unknown',
            'created_at': entry.created_at.isoformat(),
        }
    
    return JsonResponse({
        'success': True,
        'data': result,
    })


@login_required
@require_GET
def get_next_podcast_number(request):
    """
    Fetch the latest podcast number from the blog and return the next number.
    This avoids CORS issues by proxying through the Django server.
    """
    try:
        req = urllib.request.Request(
            'https://blog.binaergewitter.de/latest-show',
            headers={'User-Agent': 'Podcast-Date-Finder/1.0'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            text = response.read().decode('utf-8').strip()
            current_number = int(text)
            next_number = current_number + 1
            return JsonResponse({
                'success': True,
                'current_number': current_number,
                'next_number': next_number,
            })
    except urllib.error.URLError as e:
        logger.error(f"Error fetching podcast number: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Could not fetch podcast number from blog',
        }, status=502)
    except ValueError as e:
        logger.error(f"Error parsing podcast number: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Invalid podcast number format',
        }, status=502)
    except Exception as e:
        logger.error(f"Unexpected error fetching podcast number: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Unexpected error',
        }, status=500)


@require_GET
def export_ical(request):
    """
    Export confirmed dates as a public iCal calendar.
    No authentication required - nginx will handle caching.
    Events are scheduled from 20:00 to 23:00.
    """
    from django.conf import settings
    
    confirmed = ConfirmedDate.objects.all().order_by('date').select_related('confirmed_by')
    
    # Build iCal content
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Podcast Date Finder//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:Podcast Recording Schedule',
    ]
    
    for entry in confirmed:
        # Create datetime for 20:00-23:00 on the confirmed date
        start_dt = datetime.combine(entry.date, datetime.strptime('20:00', '%H:%M').time())
        end_dt = datetime.combine(entry.date, datetime.strptime('23:00', '%H:%M').time())
        
        # Generate a stable UID based on the date
        uid = f"{entry.date.isoformat()}-podcast@datefinder"
        
        # Format timestamps for iCal (local time)
        dtstart = start_dt.strftime('%Y%m%dT%H%M%S')
        dtend = end_dt.strftime('%Y%m%dT%H%M%S')
        dtstamp = entry.created_at.strftime('%Y%m%dT%H%M%SZ')
        
        # Get organizer info
        organizer = ''
        if entry.confirmed_by:
            organizer = entry.confirmed_by.get_full_name() or entry.confirmed_by.username
        
        # Build event
        summary = entry.description if entry.description else 'Podcast Recording'
        description = f"Confirmed by: {organizer}" if organizer else ''
        
        lines.extend([
            'BEGIN:VEVENT',
            f'UID:{uid}',
            f'DTSTAMP:{dtstamp}',
            f'DTSTART:{dtstart}',
            f'DTEND:{dtend}',
            f'SUMMARY:{_ical_escape(summary)}',
        ])
        
        if description:
            lines.append(f'DESCRIPTION:{_ical_escape(description)}')
        
        lines.append('END:VEVENT')
    
    lines.append('END:VCALENDAR')
    
    ical_content = '\r\n'.join(lines)
    
    response = HttpResponse(ical_content, content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="podcast_calendar.ics"'
    return response


def _ical_escape(text: str) -> str:
    """Escape special characters for iCal format."""
    if not text:
        return ''
    # Escape backslashes, semicolons, commas, and newlines
    text = text.replace('\\', '\\\\')
    text = text.replace(';', '\\;')
    text = text.replace(',', '\\,')
    text = text.replace('\n', '\\n')
    return text
