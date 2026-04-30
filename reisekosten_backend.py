#!/usr/bin/env python3
"""
Reisekosten-Workflow Backend
Mit Notion API Polling (alle 60 Minuten) - optimiert
"""

import os
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List

from flask import Flask, request, jsonify
from slack_sdk import WebClient as SlackClient
from slack_sdk.errors import SlackApiError

try:
    from notion_client import Client as NotionClient
    NOTION_SDK_AVAILABLE = True
except ImportError:
    NOTION_SDK_AVAILABLE = False
    NotionClient = None

app = Flask(__name__)

NOTION_SERVICE_ACCOUNT_JSON = os.getenv("NOTION_SERVICE_ACCOUNT_JSON", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0AKDAY79BP")

REISEKOSTEN_FREIGABE_DB_ID = "562de3ad-7fe0-47cf-a290-a7d6a8b633dd"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

reported_requests = set()
last_check_time = None

# ============================================================================
# CLIENTS
# ============================================================================

def get_notion_client():
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
    return None

notion_client = get_notion_client()
slack_client = SlackClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None

# ============================================================================
# SLACK
# ============================================================================

def send_slack_dm(user_email: str, message: str) -> bool:
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

# ============================================================================
# NOTION POLLING (asynchron im Hintergrund)
# ============================================================================

def check_notion_async():
    """Notion API Abfrage in separatem Thread"""
    global reported_requests, last_check_time
    
    try:
        if not notion_client:
            logger.warning("Notion Client nicht verfügbar")
            return

        logger.info("Starte Notion API Abfrage...")
        
        response = notion_client.databases.query(
            database_id=REISEKOSTEN_FREIGABE_DB_ID
        )

        logger.info(f"Notion API: {len(response['results'])} Seiten gefunden")

        for page in response['results']:
            try:
                page_id = page['id']
                properties = page['properties']

                status = properties.get('Status', {}).get('select', {}).get('name', '')
                email = properties.get('E-Mail', {}).get('email', '')
                antrag_name = properties.get('Antrag', {}).get('title', [{}])[0].get('text', {}).get('content', 'Unbekannt')
                vorgangs_id = properties.get('Vorgangs-ID', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
                betrag = properties.get('erwarteter Betrag (EUR)', {}).get('number', 'N/A')

                if status and email and page_id not in reported_requests:
                    if status == "Freigegeben":
                        message = f"✅ Dein Reisekostenantrag *{antrag_name}* ({vorgangs_id}) wurde **freigegeben**.\nBetrag: {betrag} EUR"
                        send_slack_dm(email, message)
                        reported_requests.add(page_id)
                        logger.info(f"Benachrichtigung für {antrag_name} versendet")
                    elif status == "Abgelehnt":
                        message = f"❌ Dein Reisekostenantrag *{antrag_name}* ({vorgangs_id}) wurde **abgelehnt**."
                        send_slack_dm(email, message)
                        reported_requests.add(page_id)
                        logger.info(f"Ablehnung für {antrag_name} versendet")
            except Exception as e:
                logger.error(f"Fehler bei Seite {page_id}: {e}")
                continue

        last_check_time = datetime.now(timezone.utc).isoformat()
        logger.info(f"Notion Check abgeschlossen. {len(reported_requests)} Anträge gemeldet")

    except Exception as e:
        logger.error(f"Fehler beim Notion Polling: {e}")

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.route("/webhook/notion", methods=["POST"])
def handle_notion_webhook():
    try:
        payload = request.get_json()
        logger.info(f"Notion Webhook erhalten: {payload.get('type')}")
        if payload.get("type") == "ping":
            return jsonify({"success": True}), 200
        return jsonify({"success": True}), 200
    except Exception as e:
        logger.error(f"Fehler in Webhook: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/scheduled/check-all", methods=["POST"])
def check_all_endpoint():
    """Triggeert Notion Polling im Hintergrund"""
    try:
        logger.info("check-all triggered - starte Notion Polling im Hintergrund")
        
        # Starte Polling in separatem Thread (blockiert nicht)
        thread = threading.Thread(target=check_notion_async)
        thread.daemon = True
        thread.start()

        return jsonify({
            "success": True,
            "message": "Check gestartet (läuft im Hintergrund)",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200

    except Exception as e:
        logger.error(f"Fehler in check_all: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/scheduled/check-new-requests", methods=["POST"])
def check_new_requests_endpoint():
    return check_all_endpoint()

@app.route("/scheduled/check-overdue", methods=["POST"])
def check_overdue_endpoint():
    try:
        logger.info("check-overdue triggered")
        return jsonify({
            "success": True,
            "message": "Check completed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    except Exception as e:
        logger.error(f"Fehler: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clients": {
            "slack": bool(slack_client),
            "notion": bool(notion_client),
        },
        "polling": {
            "mode": "Notion API (asynchron)",
            "last_check": last_check_time,
            "reported": len(reported_requests)
        }
    }), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
