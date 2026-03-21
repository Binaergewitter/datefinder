"""
iCal file generation for confirmed podcast dates.

This module handles generating and writing the iCal file to disk.
The file is regenerated:
- On application startup
- When a date is confirmed or unconfirmed (via ICalExportHook)
"""

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings

logger = logging.getLogger(__name__)


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


def generate_ical_content() -> str:
    """
    Generate iCal content from confirmed dates in the database.

    Returns:
        str: The complete iCal file content
    """
    # Import here to avoid circular imports during app startup
    from .models import ConfirmedDate, Reminder

    confirmed = ConfirmedDate.objects.all().order_by('date').select_related('confirmed_by')
    reminders = Reminder.objects.all().order_by('date').select_related('created_by')

    # Get timezone from settings (default: Europe/Berlin)
    tz_name = getattr(settings, 'ICAL_TIMEZONE', 'Europe/Berlin')
    tz = ZoneInfo(tz_name)

    # Build iCal content
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Binärgewitter Live Podcast Schedule//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:Binärgewitter Live Podcast Schedule',
        'X-WR-TIMEZONE:UTC',

    ]

    utc = ZoneInfo('UTC')

    for entry in confirmed:
        # Create datetime for 20:00-23:00 on the confirmed date in the configured timezone
        start_dt = datetime.combine(entry.date, datetime.strptime('20:00', '%H:%M').time(), tzinfo=tz)
        end_dt = datetime.combine(entry.date, datetime.strptime('23:00', '%H:%M').time(), tzinfo=tz)

        # Convert to UTC for iCal
        start_utc = start_dt.astimezone(utc)
        end_utc = end_dt.astimezone(utc)

        # Generate a stable UID based on the date
        uid = f"{entry.date.isoformat()}-podcast@datefinder"

        # Format timestamps for iCal in UTC (Z suffix)
        dtstart = start_utc.strftime('%Y%m%dT%H%M%SZ')
        dtend = end_utc.strftime('%Y%m%dT%H%M%SZ')
        dtstamp = entry.created_at.strftime('%Y%m%dT%H%M%SZ')

        # Get organizer info
        organizer = ''
        if entry.confirmed_by:
            organizer = entry.confirmed_by.get_full_name() or entry.confirmed_by.username

        # Build event
        summary = "Binärgewitter Podcast"
        description = entry.description if entry.description else 'Podcast Recording'
        description += f"\nConfirmed by: {organizer}" if organizer else ''

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

    for reminder in reminders:
        # Create datetime for 20:00-23:00 on the reminder date in the configured timezone
        start_dt = datetime.combine(reminder.date, datetime.strptime('20:00', '%H:%M').time(), tzinfo=tz)
        end_dt = datetime.combine(reminder.date, datetime.strptime('23:00', '%H:%M').time(), tzinfo=tz)

        # Convert to UTC for iCal
        start_utc = start_dt.astimezone(utc)
        end_utc = end_dt.astimezone(utc)

        # UID includes pk since reminder dates are not unique
        uid = f"{reminder.date.isoformat()}-reminder-{reminder.pk}@datefinder"

        dtstart = start_utc.strftime('%Y%m%dT%H%M%SZ')
        dtend = end_utc.strftime('%Y%m%dT%H%M%SZ')
        dtstamp = reminder.created_at.strftime('%Y%m%dT%H%M%SZ')

        summary = reminder.title
        description = reminder.description or ''

        creator = ''
        if reminder.created_by:
            creator = reminder.created_by.get_full_name() or reminder.created_by.username
        if creator:
            if description:
                description += f"\nCreated by: {creator}"
            else:
                description = f"Created by: {creator}"

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

    return '\r\n'.join(lines)


def generate_ical_file( ) -> Path:
    """
    Generate and write the iCal file to the configured path.

    Returns:
        Path: The path where the file was written
    """
    export_path = Path(getattr(settings, 'ICAL_EXPORT_PATH'))
    logger.debug(f"Generating iCal file at: {export_path}")

    try:
        ical_content = generate_ical_content()

        # Ensure parent directory exists
        export_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        export_path.write_text(ical_content, encoding='utf-8')

        logger.info(f"iCal file written successfully to: {export_path}")
        return export_path

    except Exception as e:
        logger.error(f"Failed to write iCal file to {export_path}: {e}", exc_info=True)
        raise
