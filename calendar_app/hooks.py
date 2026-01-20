"""
Post-action hooks for confirmed date events.

This module provides a pluggable interface for running actions after 
dates are confirmed or unconfirmed. Hooks can be used for:
- Sending notifications via Apprise
- Exporting to CSV
- Integrating with external services

To add a custom hook:
1. Create a class that inherits from PostActionHook
2. Implement on_confirm() and on_unconfirm() methods
3. Register it in HOOK_REGISTRY
"""

import logging
from abc import ABC, abstractmethod
from datetime import date as date_type
from typing import Optional
from django.conf import settings
from django.contrib.auth.models import User
from .ical import generate_ical_file

logger = logging.getLogger(__name__)

# Check if apprise is available
try:
    import apprise
    logger.info(f"Apprise library found, version: {apprise.__version__}")
except ImportError:
    logger.warning("Apprise library NOT installed. Install with: pip install apprise")


class PostActionHook(ABC):
    """
    Abstract base class for post-action hooks.
    Implement this interface to create custom hooks.
    """
    
    @abstractmethod
    def on_confirm(self, date: date_type, description: str, confirmed_by: Optional[User] = None) -> None:
        """
        Called when a date is confirmed.
        
        Args:
            date: The confirmed date
            description: Description/notes for the confirmed date
            confirmed_by: The user who confirmed the date (may be None)
        """
        pass
    
    @abstractmethod
    def on_unconfirm(self, date: date_type) -> None:
        """
        Called when a date is unconfirmed.
        
        Args:
            date: The unconfirmed date
        """
        pass


class AppriseHook(PostActionHook):
    """
    Hook that sends notifications via Apprise library.
    
    Configure via settings:
    - APPRISE_URLS: List of Apprise notification URLs
    - APPRISE_CONFIRM_TEMPLATE: Jinja2 template for confirm message (optional)
    - APPRISE_UNCONFIRM_TEMPLATE: Jinja2 template for unconfirm message (optional)
    
    Default template uses just the description.
    """
    
    def __init__(self):
        self.urls = getattr(settings, 'APPRISE_URLS', [])
        self.confirm_template = getattr(
            settings, 
            'APPRISE_CONFIRM_TEMPLATE', 
            '{{ description }}'
        )
        self.unconfirm_template = getattr(
            settings, 
            'APPRISE_UNCONFIRM_TEMPLATE', 
            'Date {{ date }} has been unconfirmed.'
        )
        logger.debug(f"AppriseHook initialized with {len(self.urls)} URL(s)")
        logger.debug(f"Confirm template: {self.confirm_template}")
        logger.debug(f"Unconfirm template: {self.unconfirm_template}")
    
    def _render_template(self, template: str, context: dict) -> str:
        """Render a Jinja2 template with the given context."""
        try:
            from jinja2 import Template
            t = Template(template)
            return t.render(**context)
        except Exception as e:
            logger.error(f"Error rendering template: {e}")
            return str(context.get('description', ''))
    
    def _send_notification(self, message: str, title: str = "") -> None:
        """Send notification to all configured Apprise URLs."""
        if not self.urls:
            logger.debug("No Apprise URLs configured, skipping notification")
            return
        
        logger.debug(f"Preparing to send Apprise notification. URLs configured: {len(self.urls)}")
        logger.debug(f"Notification title: {title}")
        logger.debug(f"Notification message: {message}")
        
        try:
            import apprise
            
            logger.debug(f"Apprise version: {apprise.__version__}")
            
            apobj = apprise.Apprise()
            for idx, url in enumerate(self.urls):
                # Mask sensitive parts of URL for logging
                masked_url = url.split('://')[0] + '://***' if '://' in url else '***'
                logger.debug(f"Adding Apprise URL {idx + 1}/{len(self.urls)}: {masked_url}")
                add_result = apobj.add(url)
                logger.debug(f"URL {idx + 1} add result: {add_result}")
            
            logger.debug(f"Total services loaded: {len(apobj)}")
            
            logger.info(f"Sending notification via Apprise to {len(apobj)} service(s)")
            success = apobj.notify(
                body=message,
                title=title,
            )
            
            if success:
                logger.info(f"Apprise notification sent successfully to all services")
            else:
                logger.warning(f"Apprise notification failed or partially failed")
                
        except ImportError:
            logger.warning("Apprise library not installed. Run: pip install apprise")
        except Exception as e:
            logger.error(f"Error sending Apprise notification: {e}", exc_info=True)
    
    def on_confirm(self, date: date_type, description: str, confirmed_by: Optional[User] = None) -> None:
        if not self.urls:
            logger.debug("Skipping Apprise notification for confirm (no URLs configured)")
            return
        
        logger.debug(f"Preparing confirm notification for date: {date}")
            
        context = {
            'date': date.isoformat(),
            'date_formatted': date.strftime('%A, %B %d, %Y'),
            'description': description,
            'confirmed_by': confirmed_by.get_full_name() or confirmed_by.username if confirmed_by else 'Unknown',
            'site_url': getattr(settings, 'SITE_URL', ''),
        }
        
        logger.debug(f"Notification context: {context}")
        
        message = self._render_template(self.confirm_template, context)
        logger.debug(f"Rendered message from template: {message}")
        
        self._send_notification(message)
    
    def on_unconfirm(self, date: date_type) -> None:
        if not self.urls:
            logger.debug("Skipping Apprise notification for unconfirm (no URLs configured)")
            return
        
        logger.debug(f"Preparing unconfirm notification for date: {date}")
            
        context = {
            'date': date.isoformat(),
            'date_formatted': date.strftime('%A, %B %d, %Y'),
        }
        
        logger.debug(f"Notification context: {context}")
        
        message = self._render_template(self.unconfirm_template, context)
        logger.debug(f"Rendered message from template: {message}")
        
        self._send_notification(message)


class LoggingHook(PostActionHook):
    """
    Simple hook that logs confirm/unconfirm events.
    Useful for debugging and audit trails.
    """
    
    def on_confirm(self, date: date_type, description: str, confirmed_by: Optional[User] = None) -> None:
        user_name = confirmed_by.get_full_name() or confirmed_by.username if confirmed_by else 'Unknown'
        logger.info(f"Date confirmed: {date} by {user_name} - {description}")
    
    def on_unconfirm(self, date: date_type) -> None:
        logger.info(f"Date unconfirmed: {date}")


class ICalExportHook(PostActionHook):
    """
    Hook that regenerates the iCal file when dates are confirmed/unconfirmed.
    The file is written to the path configured in ICAL_EXPORT_PATH.
    """
    
    def on_confirm(self, date: date_type, description: str, confirmed_by: Optional[User] = None) -> None:
        try:
            path = generate_ical_file()
            logger.info(f"iCal file regenerated after confirming {date}: {path}")
        except Exception as e:
            logger.error(f"Failed to regenerate iCal file after confirming {date}: {e}")
    
    def on_unconfirm(self, date: date_type) -> None:
        try:
            path = generate_ical_file()
            logger.info(f"iCal file regenerated after unconfirming {date}: {path}")
        except Exception as e:
            logger.error(f"Failed to regenerate iCal file after unconfirming {date}: {e}")


# Registry of active hooks
# Add or remove hooks here to enable/disable them
HOOK_REGISTRY: list[PostActionHook] = [
    LoggingHook(),
    AppriseHook(),
    ICalExportHook(),
]


def run_confirm_hooks(date: date_type, description: str, confirmed_by: Optional[User] = None) -> None:
    """
    Run all registered hooks for a confirm event.
    
    Args:
        date: The confirmed date
        description: Description for the confirmed date
        confirmed_by: User who confirmed the date
    """
    logger.debug(f"run_confirm_hooks called for date {date}, description: {description}")
   
    for hook in HOOK_REGISTRY:
        try:
            logger.debug(f"Running hook: {hook.__class__.__name__}")
            hook.on_confirm(date, description, confirmed_by)
            logger.debug(f"Hook {hook.__class__.__name__} completed successfully")
        except Exception as e:
            logger.error(f"Error running confirm hook {hook.__class__.__name__}: {e}", exc_info=True)


def run_unconfirm_hooks(date: date_type) -> None:
    """
    Run all registered hooks for an unconfirm event.
    
    Args:
        date: The unconfirmed date
    """
    logger.debug(f"run_unconfirm_hooks called for date {date}")
   
    for hook in HOOK_REGISTRY:
        try:
            logger.debug(f"Running hook: {hook.__class__.__name__}")
            hook.on_unconfirm(date)
            logger.debug(f"Hook {hook.__class__.__name__} completed successfully")
        except Exception as e:
            logger.error(f"Error running unconfirm hook {hook.__class__.__name__}: {e}", exc_info=True)
