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
    from .models import ConfirmedDate
    
    confirmed = ConfirmedDate.objects.all().order_by('date').select_related('confirmed_by')
    
    # Build iCal content
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Binärgewitter Live Podcast Schedule//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:Binärgewitter Live Podcast Schedule',
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
