import json
import logging
import urllib.error
import urllib.request
from datetime import date as date_type
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .hooks import run_confirm_hooks, run_unconfirm_hooks
from .models import Availability, ConfirmedDate, Reminder

logger = logging.getLogger(__name__)


@login_required
def calendar_view(request):
    """
    Main calendar view.
    """
    return render(request, 'calendar_app/calendar.html', {
        'user': request.user,
        'active_nav': 'calendar',
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
        'active_nav': 'confirm',
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

    # Check if date has 1+ availabilities
    # update
    availability_count = Availability.count_available(target_date)
    if availability_count < 1:
        return JsonResponse({'error': 'Date must have at least 1 available users'}, status=400)

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
    Serve the iCal calendar file.
    No authentication required - nginx will handle caching.
    The file is pre-generated and written to disk on startup and when dates change.
    """
    from pathlib import Path

    export_path = Path(getattr(settings, 'ICAL_EXPORT_PATH', 'calendar.ics'))

    if not export_path.exists():
        # Generate the file if it doesn't exist
        from .ical import generate_ical_file
        try:
            generate_ical_file()
        except Exception as e:
            logger.error(f"Failed to generate iCal file: {e}")
            return HttpResponse("Calendar not available", status=503)

    try:
        ical_content = export_path.read_text(encoding='utf-8')
        response = HttpResponse(ical_content, content_type='text/calendar; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="podcast_calendar.ics"'
        return response
    except Exception as e:
        logger.error(f"Failed to read iCal file from {export_path}: {e}")
        return HttpResponse("Calendar not available", status=503)


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


@login_required
def reminders_view(request):
    """
    View showing all reminders with inline create/edit/delete.
    Future reminders are sorted ascending (next reminder first).
    Past reminders are provided separately for a collapsible section.
    """
    today = date_type.today()
    future_reminders = (
        Reminder.objects.filter(date__gte=today)
        .select_related('created_by')
        .order_by('date')
    )
    past_reminders = (
        Reminder.objects.filter(date__lt=today)
        .select_related('created_by')
        .order_by('-date')
    )
    return render(request, 'calendar_app/reminders.html', {
        'user': request.user,
        'future_reminders': future_reminders,
        'past_reminders': past_reminders,
        'active_nav': 'reminders',
        'today': today,
    })


@login_required
@require_POST
def api_create_reminder(request):
    """
    Create a new reminder entry.
    """
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    title = body.get('title', '').strip()
    date_str = body.get('date', '').strip()
    description = body.get('description', '').strip()

    if not title:
        return JsonResponse({'error': 'Title is required'}, status=400)
    if not date_str:
        return JsonResponse({'error': 'Date is required'}, status=400)

    try:
        reminder_date = date_type.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)

    reminder = Reminder.objects.create(
        title=title,
        date=reminder_date,
        description=description,
        created_by=request.user,
    )

    # Regenerate iCal file
    from .ical import generate_ical_file
    try:
        generate_ical_file()
    except Exception as e:
        logger.error(f"Failed to regenerate iCal after creating reminder: {e}")

    return JsonResponse({
        'success': True,
        'reminder': {
            'id': reminder.pk,
            'title': reminder.title,
            'date': reminder.date.isoformat(),
            'date_display': reminder.date.strftime('%A, %B %d, %Y'),
            'description': reminder.description,
            'created_by': reminder.created_by.get_full_name() or reminder.created_by.username if reminder.created_by else '',
        },
    })


@login_required
@require_POST
def api_update_reminder(request, pk):
    """
    Update an existing reminder entry.
    """
    try:
        reminder = Reminder.objects.get(pk=pk)
    except Reminder.DoesNotExist:
        return JsonResponse({'error': 'Reminder not found'}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    title = body.get('title', '').strip()
    date_str = body.get('date', '').strip()
    description = body.get('description', '').strip()

    if not title:
        return JsonResponse({'error': 'Title is required'}, status=400)
    if not date_str:
        return JsonResponse({'error': 'Date is required'}, status=400)

    try:
        reminder_date = date_type.fromisoformat(date_str)
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)

    reminder.title = title
    reminder.date = reminder_date
    reminder.description = description
    reminder.save()

    # Regenerate iCal file
    from .ical import generate_ical_file
    try:
        generate_ical_file()
    except Exception as e:
        logger.error(f"Failed to regenerate iCal after updating reminder: {e}")

    return JsonResponse({
        'success': True,
        'reminder': {
            'id': reminder.pk,
            'title': reminder.title,
            'date': reminder.date.isoformat(),
            'date_display': reminder.date.strftime('%A, %B %d, %Y'),
            'description': reminder.description,
            'created_by': reminder.created_by.get_full_name() or reminder.created_by.username if reminder.created_by else '',
        },
    })


@login_required
@require_POST
def api_delete_reminder(request, pk):
    """
    Delete a reminder entry.
    """
    try:
        reminder = Reminder.objects.get(pk=pk)
    except Reminder.DoesNotExist:
        return JsonResponse({'error': 'Reminder not found'}, status=404)

    reminder.delete()

    # Regenerate iCal file
    from .ical import generate_ical_file
    try:
        generate_ical_file()
    except Exception as e:
        logger.error(f"Failed to regenerate iCal after deleting reminder: {e}")

    return JsonResponse({'success': True})
