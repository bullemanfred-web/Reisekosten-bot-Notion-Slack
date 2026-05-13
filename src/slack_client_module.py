#!/usr/bin/env python3
"""
Slack Client Module
Slack API Integration
"""

import logging
from typing import Optional

from slack_sdk import WebClient as SlackClient
from slack_sdk.errors import SlackApiError

from config import SLACK_BOT_TOKEN

logger = logging.getLogger(__name__)

def get_slack_client() -> Optional[SlackClient]:
    """Initialisiert Slack Client"""
    if not SLACK_BOT_TOKEN:
        logger.warning("Slack nicht konfiguriert (SLACK_BOT_TOKEN leer)")
        return None

    try:
        client = SlackClient(token=SLACK_BOT_TOKEN)
        logger.info("✅ Slack Client initialisiert")
        return client
    except Exception as e:
        logger.error(f"Slack Client Fehler: {e}")
        return None

def send_slack_dm(slack_client: Optional[SlackClient], user_email: str, message) -> bool:
    """
    Sendet Slack DM an Benutzer
    message: str (einfach) oder dict mit blocks (formatiert)
    """
    try:
        if not slack_client:
            logger.warning("Slack nicht konfiguriert")
            return False

        logger.info(f"Versuche, DM an {user_email} zu senden...")
        users = slack_client.users_lookupByEmail(email=user_email)
        user_id = users["user"]["id"]

        # Unterstütze sowohl einfache Text-Messages als auch Block Kit
        if isinstance(message, dict):
            # Block Kit Message
            slack_client.chat_postMessage(channel=user_id, **message)
        else:
            # Text Message
            slack_client.chat_postMessage(channel=user_id, text=message)

        logger.info(f"✅ DM versendet an {user_email} (User ID: {user_id})")
        return True

    except SlackApiError as e:
        logger.error(f"Slack API Fehler: {e.response['error']}")
        return False
    except Exception as e:
        logger.error(f"Fehler beim DM-Versand: {e}")
        return False
