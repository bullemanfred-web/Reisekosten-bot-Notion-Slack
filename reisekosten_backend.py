#!/usr/bin/env python3
"""
Reisekosten-Workflow Backend
Vereinfachte Version ohne Google Drive
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict
import hashlib
import hmac

from flask import Flask, request, jsonify
from slack_sdk import WebClient as SlackClient
from slack_sdk.errors import SlackApiError

# Notion SDK
try:
    from notion_client import Client as NotionClient
    NOTION_SDK_AVAILABLE = True
except ImportError:
    NOTION_SDK_AVAILABLE = False
    NotionClient = None

app = Flask(__name__)

# Environment Variables
NOTION_WEBHOOK_SECRET = os.getenv("NOTION_WEBHOOK_SECRET", "")
NOTION_SERVICE_ACCOUNT_JSON = os.getenv("NOTION_SERVICE_ACCOUNT_JSON", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0AKDAY79BP")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# NOTION CLIENT
# ============================================================================

def get_notion_client():
    """Initialisiert Notion Client"""
    if not NOTION_SDK_AVAILABLE:
        return None
    
    if NOTION_SERVICE_ACCOUNT_JSON:
        try:
            sa_creds = json.loads(NOTION_SERVICE_ACCOUNT_JSON)
            token = sa_creds.get("access_token") or sa_creds.get("token")
            if token:
                logger.info("Notion Client initialisiert")
                return NotionClient(auth=token)
        except Exception as e:
            logger.error(f"Fehler beim Parsen von NOTION_SERVICE_ACCOUNT_JSON: {e}")
    
    logger.warning("Kein Notion Authentication konfiguriert")
    return None

notion_client = get_notion_client()

# ============================================================================
# SLACK CLIENT
# ============================================================================

slack_client = SlackClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None

# ============================================================================
# SLACK BENACHRICHTIGUNGEN
# ============================================================================

def send_slack_dm(user_email: str, message: str) -> bool:
    """Sendet Slack DM"""
    try:
        if not slack_client:
            logger.warning("Slack nicht konfiguriert")
            return False
        
        users = slack_client.users_lookupByEmail(email=user_email)
        user_id = users["user"]["id"]
        slack_client.chat_postMessage(channel=user_id, text=message)
        logger.info(f"DM an {user_email} versendet")
        return True
    except SlackApiError as e:
        logger.error(f"Slack Fehler: {e}")
        return False

def send_slack_channel_message(message: str) -> bool:
    """Sendet Nachricht an Slack Kanal"""
    try:
        if not slack_client:
            logger.warning("Slack nicht konfiguriert")
            return False
        
        slack_client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=message)
        logger.info(f"Nachricht an {SLACK_CHANNEL_ID} versendet")
        return True
    except SlackApiError as e:
        logger.error(f"Slack Fehler: {e}")
        return False

# ============================================================================
# WEBHOOK HANDLER
# ============================================================================

@app.route("/webhook/notion", methods=["POST"])
def handle_notion_webhook():
    """Verarbeitet Notion Webhooks"""
    try:
        signature = request.headers.get("X-Notion-Signature", "")
        payload = request.get_json()
        logger.info(f"Notion Webhook erhalten: {payload.get('type')}")
        
        if payload.get("type") == "ping":
            return jsonify({"success": True}), 200
        
        return jsonify({"success": True}), 200
    
    except Exception as e:
        logger.error(f"Fehler in Webhook Handler: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# SCHEDULED ENDPOINTS
# ============================================================================

@app.route("/scheduled/check-new-requests", methods=["POST"])
def check_new_requests_endpoint():
    """Endpoint für Cloud Scheduler"""
    try:
        logger.info("check-new-requests triggered")
        
        if not notion_client:
            logger.warning("Notion Client nicht verfügbar")
            return jsonify({"error": "Notion not configured"}), 503
        
        return jsonify({
            "success": True,
            "message": "Check completed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    
    except Exception as e:
        logger.error(f"Fehler in check_new_requests: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/scheduled/check-overdue", methods=["POST"])
def check_overdue_endpoint():
    """Endpoint für Cloud Scheduler"""
    try:
        logger.info("check-overdue triggered")
        
        if not notion_client:
            logger.warning("Notion Client nicht verfügbar")
            return jsonify({"error": "Notion not configured"}), 503
        
        return jsonify({
            "success": True,
            "message": "Overdue check completed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    
    except Exception as e:
        logger.error(f"Fehler in check_overdue: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health Check"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clients": {
            "slack_configured": bool(slack_client),
            "notion_configured": bool(notion_client),
        },
        "notion_sdk": {
            "available": NOTION_SDK_AVAILABLE,
            "service_account_configured": bool(NOTION_SERVICE_ACCOUNT_JSON),
        }
    }), 200

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
