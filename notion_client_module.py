#!/usr/bin/env python3
"""
Notion Client Module
Notion API Integration
"""

import json
import logging
from typing import Optional

try:
    from notion_client import Client as NotionClient
    from notion_client.errors import APIResponseError
    NOTION_SDK_AVAILABLE = True
except ImportError:
    NOTION_SDK_AVAILABLE = False
    NotionClient = None
    APIResponseError = None

from config import NOTION_SERVICE_ACCOUNT_JSON

logger = logging.getLogger(__name__)

def get_notion_client() -> Optional[NotionClient]:
    """Initialisiert Notion Client mit ausführlichem Logging"""
    logger.info("=" * 80)
    logger.info("NOTION CLIENT INITIALIZATION")
    logger.info("=" * 80)

    if not NOTION_SDK_AVAILABLE:
        logger.error("notion-client nicht installiert")
        return None

    if not NOTION_SERVICE_ACCOUNT_JSON:
        logger.error("NOTION_SERVICE_ACCOUNT_JSON Umgebungsvariable ist LEER")
        return None

    logger.info(f"Token länge: {len(NOTION_SERVICE_ACCOUNT_JSON)} Zeichen")

    try:
        sa_creds = json.loads(NOTION_SERVICE_ACCOUNT_JSON)
        logger.info(f"JSON geparst. Keys: {list(sa_creds.keys())}")

        token = sa_creds.get("access_token") or sa_creds.get("token")
        if not token:
            logger.error(f"Kein 'access_token' oder 'token' in JSON gefunden. Keys: {list(sa_creds.keys())}")
            return None

        logger.info(f"Token gefunden: {token[:30]}...")

        client = NotionClient(auth=token)
        logger.info("✅ Notion Client erfolgreich erstellt")
        logger.info("=" * 80)
        return client

    except json.JSONDecodeError as e:
        logger.error(f"JSON Parse Fehler: {e}")
        return None
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {e}")
        return None
