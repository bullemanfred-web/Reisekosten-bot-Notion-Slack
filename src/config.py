#!/usr/bin/env python3
"""
Configuration Module
Alle Umgebungsvariablen und Konstanten
"""

import os
import json
import base64
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# ENVIRONMENT VARIABLES
# ============================================================================

NOTION_SERVICE_ACCOUNT_JSON = os.getenv("NOTION_SERVICE_ACCOUNT_JSON", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0AKDAY79BP")

# Notion Database IDs
REISEKOSTEN_FREIGABE_DB_ID = os.getenv("REISEKOSTEN_FREIGABE_DB_ID", "6884ef9fe113402e8a932079a90e85a2")
REISEKOSTEN_RECHNUNG_DB_ID = os.getenv("REISEKOSTEN_RECHNUNG_DB_ID", "d2a81613f5b64d2580042d717ebd03b2")

# Cloud Storage
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "reisekosten-workflow-state")
GCS_STATE_FILE = "reported_requests.json"

# Google Drive
# Try to get base64-encoded credentials first (from Cloud Run deployment)
GOOGLE_DRIVE_CREDENTIALS_B64 = os.getenv("GOOGLE_DRIVE_CREDENTIALS_B64", "")
if GOOGLE_DRIVE_CREDENTIALS_B64:
    try:
        GOOGLE_DRIVE_CREDENTIALS_JSON = base64.b64decode(GOOGLE_DRIVE_CREDENTIALS_B64).decode('utf-8')
    except Exception as e:
        logger.error(f"Error decoding base64 credentials: {e}")
        GOOGLE_DRIVE_CREDENTIALS_JSON = ""
else:
    # Fallback to direct JSON (for local development)
    GOOGLE_DRIVE_CREDENTIALS_JSON = os.getenv("GOOGLE_DRIVE_CREDENTIALS_JSON", "")

GOOGLE_DRIVE_CREDENTIALS = {}
logger.info(f"📋 GOOGLE_DRIVE_CREDENTIALS_B64 länge: {len(GOOGLE_DRIVE_CREDENTIALS_B64)} Zeichen")
logger.info(f"📋 GOOGLE_DRIVE_CREDENTIALS_JSON länge: {len(GOOGLE_DRIVE_CREDENTIALS_JSON)} Zeichen")

if GOOGLE_DRIVE_CREDENTIALS_JSON:
    try:
        GOOGLE_DRIVE_CREDENTIALS = json.loads(GOOGLE_DRIVE_CREDENTIALS_JSON)
        logger.info(f"✅ GOOGLE_DRIVE_CREDENTIALS geparst. Keys: {list(GOOGLE_DRIVE_CREDENTIALS.keys())}")
    except json.JSONDecodeError as e:
        logger.error(f"❌ Error parsing GOOGLE_DRIVE_CREDENTIALS_JSON: {e}")
        GOOGLE_DRIVE_CREDENTIALS = {}
else:
    logger.warning(f"⚠️ GOOGLE_DRIVE_CREDENTIALS_JSON ist leer")

GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "1wCo_3qi6QPeRDm2uLOrOBD7AylqnUGmw")
