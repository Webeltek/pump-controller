# webhook.py - Add pump state change tracking
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _normalize_webhook_urls(webhook_urls):
    """Normalize webhook URLs into a list of clean endpoint roots."""
    if webhook_urls is None:
        return []

    if isinstance(webhook_urls, str):
        items = [part.strip() for part in webhook_urls.split(',') if part.strip()]
    elif isinstance(webhook_urls, (list, tuple, set)):
        items = [str(url).strip() for url in webhook_urls if str(url).strip()]
    else:
        items = [str(webhook_urls).strip()] if str(webhook_urls).strip() else []

    return [item.rstrip('/') for item in items if item]


class WebhookClient:
    """
    Pushes updates from Flask to external React/Express app
    """
    def __init__(self, webhook_urls, app=None):
        self.webhook_urls = _normalize_webhook_urls(webhook_urls)
        self.webhook_url = self.webhook_urls[0] if self.webhook_urls else None
        self.app = app
        self.enabled = bool(self.webhook_urls)
        self.last_pump_state = None  # Track last state to avoid duplicates
        
        if self.enabled:
            logger.info(f"Webhook client initialized with URLs: {self.webhook_urls}")
        else:
            logger.warning("Webhook client disabled - no URL configured")
    
    def send_immediate(self, event_type, data):
        """Send an immediate update (bypasses batching)"""
        if not self.enabled:
            return
        
        # Track pump state to avoid duplicate sends
        if event_type == 'pump_status':
            current_state = data.get('running')
            if self.last_pump_state == current_state:
                logger.debug(f"Skipping duplicate pump status (state: {current_state})")
                return
            self.last_pump_state = current_state
        
        payload = {
            'event': event_type,
            'timestamp': datetime.utcnow().isoformat(),
            'immediate': True,
            'data': data
        }
        
        for webhook_url in self.webhook_urls:
            try:
                response = requests.post(
                    f"{webhook_url}/webhook/pump-status",
                    json=payload,
                    timeout=5
                )
                if response.status_code == 200:
                    logger.info(f"Immediate update sent: {event_type} -> {webhook_url}")
                else:
                    logger.warning(f"Immediate update failed for {webhook_url}: {response.status_code}")
            except Exception as e:
                logger.error(f"Immediate update error for {webhook_url}: {e}")

# Global webhook client
webhook_client = None

def init_webhook(webhook_urls, app=None):
    """Initialize the webhook client"""
    global webhook_client
    webhook_client = WebhookClient(webhook_urls, app)
    return webhook_client

def push_immediate(event_type, data):
    """Convenience function for immediate updates"""
    if webhook_client:
        webhook_client.send_immediate(event_type, data)