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

logger = logging.getLogger(__name__)


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
    
    def _render_template(self, template: str, context: dict) -> str:
        """Render a Jinja2 template with the given context."""
        try:
            from jinja2 import Template
            t = Template(template)
            return t.render(**context)
        except Exception as e:
            logger.error(f"Error rendering template: {e}")
            return str(context.get('description', ''))
    
    def _send_notification(self, message: str, title: str = "Podcast Date Finder") -> None:
        """Send notification to all configured Apprise URLs."""
        if not self.urls:
            logger.debug("No Apprise URLs configured, skipping notification")
            return
        
        try:
            import apprise
            
            apobj = apprise.Apprise()
            for url in self.urls:
                apobj.add(url)
            
            success = apobj.notify(
                body=message,
                title=title,
            )
            
            if success:
                logger.info(f"Apprise notification sent successfully")
            else:
                logger.warning(f"Apprise notification may have failed")
                
        except ImportError:
            logger.warning("Apprise library not installed. Run: pip install apprise")
        except Exception as e:
            logger.error(f"Error sending Apprise notification: {e}")
    
    def on_confirm(self, date: date_type, description: str, confirmed_by: Optional[User] = None) -> None:
        if not self.urls:
            return
            
        context = {
            'date': date.isoformat(),
            'date_formatted': date.strftime('%A, %B %d, %Y'),
            'description': description,
            'confirmed_by': confirmed_by.get_full_name() or confirmed_by.username if confirmed_by else 'Unknown',
            'site_url': getattr(settings, 'SITE_URL', ''),
        }
        
        message = self._render_template(self.confirm_template, context)
        self._send_notification(message, title="📅 Podcast Date Confirmed")
    
    def on_unconfirm(self, date: date_type) -> None:
        if not self.urls:
            return
            
        context = {
            'date': date.isoformat(),
            'date_formatted': date.strftime('%A, %B %d, %Y'),
        }
        
        message = self._render_template(self.unconfirm_template, context)
        self._send_notification(message, title="❌ Podcast Date Unconfirmed")


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


# Registry of active hooks
# Add or remove hooks here to enable/disable them
HOOK_REGISTRY: list[PostActionHook] = [
    LoggingHook(),
    AppriseHook(),
]


def run_confirm_hooks(date: date_type, description: str, confirmed_by: Optional[User] = None) -> None:
    """
    Run all registered hooks for a confirm event.
    
    Args:
        date: The confirmed date
        description: Description for the confirmed date
        confirmed_by: User who confirmed the date
    """
    for hook in HOOK_REGISTRY:
        try:
            hook.on_confirm(date, description, confirmed_by)
        except Exception as e:
            logger.error(f"Error running confirm hook {hook.__class__.__name__}: {e}")


def run_unconfirm_hooks(date: date_type) -> None:
    """
    Run all registered hooks for an unconfirm event.
    
    Args:
        date: The unconfirmed date
    """
    for hook in HOOK_REGISTRY:
        try:
            hook.on_unconfirm(date)
        except Exception as e:
            logger.error(f"Error running unconfirm hook {hook.__class__.__name__}: {e}")
