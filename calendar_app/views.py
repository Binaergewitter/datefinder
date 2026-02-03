import json
import logging
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date as date_type, datetime, timedelta
import uuid
from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Availability, ConfirmedDate, RSSFeed, Note
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
def news_view(request):
    """
    RSS News view.
    """
    return render(request, 'calendar_app/news.html', {
        'user': request.user,
    })


@login_required
def rss_notes_view(request):
    """
    Combined RSS + Notes view.
    """
    return render(request, 'calendar_app/rss_notes.html', {
        'user': request.user,
    })


@login_required
def notes_view(request):
    """
    Notes view.
    """
    return render(request, 'calendar_app/notes.html', {
        'user': request.user,
    })


def _clean_text(text: str) -> str:
    if not text:
        return ''
    return ' '.join(text.split()).strip()


def _parse_rss(xml_text: str, max_items: int = 20):
    """
    Very small RSS/Atom parser using stdlib ElementTree.
    Returns list of {title, link, published, source_title}.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = []

    # RSS 2.0
    channel = root.find('channel')
    if channel is not None:
        source_title = _clean_text(channel.findtext('title'))
        for item in channel.findall('item'):
            title = _clean_text(item.findtext('title'))
            link = _clean_text(item.findtext('link'))
            pub = _clean_text(item.findtext('pubDate') or item.findtext('dc:date'))
            if title or link:
                items.append({
                    'title': title or link,
                    'link': link,
                    'published': pub,
                    'source_title': source_title,
                })
            if len(items) >= max_items:
                break
        return items

    # Atom
    if root.tag.endswith('feed'):
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        source_title = _clean_text(root.findtext('atom:title', namespaces=ns) or root.findtext('title'))
        for entry in root.findall('atom:entry', namespaces=ns) + root.findall('entry'):
            title = _clean_text(entry.findtext('atom:title', namespaces=ns) or entry.findtext('title'))
            link = ''
            link_el = entry.find('atom:link', namespaces=ns) or entry.find('link')
            if link_el is not None:
                link = link_el.attrib.get('href', '')
            pub = _clean_text(entry.findtext('atom:updated', namespaces=ns) or entry.findtext('updated') or entry.findtext('atom:published', namespaces=ns) or entry.findtext('published'))
            if title or link:
                items.append({
                    'title': title or link,
                    'link': link,
                    'published': pub,
                    'source_title': source_title,
                })
            if len(items) >= max_items:
                break

    return items


def _fetch_feed(url: str, timeout: int = 6) -> list:
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Podcast-Date-Finder/1.0'}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_type = response.headers.get('Content-Type', '')
        charset = 'utf-8'
        if 'charset=' in content_type:
            charset = content_type.split('charset=')[-1].split(';')[0].strip() or 'utf-8'
        xml_text = response.read().decode(charset, errors='replace')
        return _parse_rss(xml_text)


@login_required
@require_GET
def get_rss_feeds(request):
    feeds = RSSFeed.objects.filter(user=request.user).order_by('created_at')
    data = []
    for feed in feeds:
        data.append({
            'id': feed.id,
            'title': feed.title,
            'url': feed.url,
            'is_active': feed.is_active,
        })
    return JsonResponse({'success': True, 'data': data})


@login_required
@require_POST
def add_rss_feed(request):
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    url = (body.get('url') or '').strip()
    title = (body.get('title') or '').strip()

    if not url:
        return JsonResponse({'success': False, 'error': 'URL is required'}, status=400)

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return JsonResponse({'success': False, 'error': 'URL must start with http or https'}, status=400)

    feed, created = RSSFeed.objects.get_or_create(
        user=request.user,
        url=url,
        defaults={'title': title},
    )
    if not created and title:
        feed.title = title
        feed.save(update_fields=['title', 'updated_at'])

    return JsonResponse({
        'success': True,
        'data': {
            'id': feed.id,
            'title': feed.title,
            'url': feed.url,
            'is_active': feed.is_active,
        }
    })


@login_required
@require_POST
def delete_rss_feed(request, feed_id):
    deleted, _ = RSSFeed.objects.filter(id=feed_id, user=request.user).delete()
    if not deleted:
        return JsonResponse({'success': False, 'error': 'Feed not found'}, status=404)
    return JsonResponse({'success': True})


@login_required
@require_POST
def toggle_rss_feed(request, feed_id):
    try:
        feed = RSSFeed.objects.get(id=feed_id, user=request.user)
    except RSSFeed.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Feed not found'}, status=404)

    feed.is_active = not feed.is_active
    feed.save(update_fields=['is_active', 'updated_at'])
    return JsonResponse({'success': True, 'data': {'id': feed.id, 'is_active': feed.is_active}})


@login_required
@require_GET
def get_news(request):
    feeds = RSSFeed.objects.filter(user=request.user, is_active=True).order_by('created_at')
    limit = request.GET.get('limit')
    try:
        limit = int(limit) if limit is not None else 30
    except ValueError:
        limit = 30
    limit = max(5, min(100, limit))

    items = []
    for feed in feeds:
        try:
            feed_items = _fetch_feed(feed.url, timeout=6)
            for item in feed_items:
                item['source_title'] = item.get('source_title') or (feed.title or feed.url)
                items.append(item)
        except Exception as e:
            logger.warning(f"Failed to fetch RSS feed {feed.url}: {e}")

    # Preserve source order, but cap results
    items = items[:limit]

    return JsonResponse({'success': True, 'data': items})


@login_required
@require_GET
def get_notes(request):
    notes = Note.objects.filter(user=request.user).order_by('-created_at')
    data = []
    for note in notes:
        data.append({
            'id': note.id,
            'text': note.text,
            'created_at': note.created_at.isoformat(),
        })
    return JsonResponse({'success': True, 'data': data})


@login_required
@require_POST
def add_note(request):
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    text = (body.get('text') or '').strip()
    if not text:
        return JsonResponse({'success': False, 'error': 'Note text is required'}, status=400)

    note = Note.objects.create(user=request.user, text=text)
    return JsonResponse({
        'success': True,
        'data': {
            'id': note.id,
            'text': note.text,
            'created_at': note.created_at.isoformat(),
        }
    })


@login_required
@require_POST
def delete_note(request, note_id):
    deleted, _ = Note.objects.filter(id=note_id, user=request.user).delete()
    if not deleted:
        return JsonResponse({'success': False, 'error': 'Note not found'}, status=404)
    return JsonResponse({'success': True})


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
