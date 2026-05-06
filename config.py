#!/usr/bin/env python3
"""
Configuration Module
Alle Umgebungsvariablen und Konstanten
"""

import os

# ============================================================================
# ENVIRONMENT VARIABLES
# ============================================================================

NOTION_SERVICE_ACCOUNT_JSON = os.getenv("NOTION_SERVICE_ACCOUNT_JSON", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0AKDAY79BP")

# Notion Database IDs
REISEKOSTEN_FREIGABE_DB_ID = os.getenv("REISEKOSTEN_FREIGABE_DB_ID", "6884ef9fe113402e8a932079a90e85a2")
REISEKOSTEN_RECHNUNG_DB_ID = os.getenv("REISEKOSTEN_RECHNUNG_DB_ID", "dd3dd27e-a33c-4203-a00e-b70e9c0ae891")

# Cloud Storage
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "reisekosten-workflow-state")
GCS_STATE_FILE = "reported_requests.json"
