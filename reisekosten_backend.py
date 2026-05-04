#!/usr/bin/env python3
"""
Reisekosten-Workflow Backend v3
Mit Channel Notifications für neue Anträge + Status-Änderungen
"""

import os
import json
import logging
import threading
from datetime import datetime, timezone

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

NOTION_SERVICE_ACCOUNT_JSON = os.getenv("NOTION_SERVICE_ACCOUNT_JSON", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0AKDAY79BP")

REISEKOSTEN_FREIGABE_DB_ID = "6884ef9fe113402e8a932079a90e85a2"

reported_requests = {}
last_check_time = None

def get_notion_client():
    if not NOTION_SDK_AVAILABLE or not NOTION_SERVICE_ACCOUNT_JSON:
        return None
    try:
        sa_creds = json.loads(NOTION_SERVICE_ACCOUNT_JSON)
        token = sa_creds.get("access_token") or sa_creds.get("token")
        if token:
            logger.info("✅ Notion Client initialisiert")
            return NotionClient(auth=token)
    except Exception as e:
        logger.error(f"Notion Client Fehler: {e}")
    return None

notion_client = get_notion_client()
slack_client = SlackClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None

def send_slack_dm(user_email: str, message: str) -> bool:
    try:
        if not slack_client:
            return False
        users = slack_client.users_lookupByEmail(email=user_email)
        user_id = users["user"]["id"]
        slack_client.chat_postMessage(channel=user_id, text=message)
        logger.info(f"✅ DM versendet an {user_email}")
        return True
    except Exception as e:
        logger.error(f"Slack DM Fehler: {e}")
        return False

def send_slack_channel_message(message: str) -> bool:
    try:
        if not slack_client:
            return False
        slack_client.chat_postMessage(channel=SLACK_CHANNEL_ID, text=message)
        logger.info(f"✅ Channel Message versendet an {SLACK_CHANNEL_ID}")
        return True
    except Exception as e:
        logger.error(f"Slack Channel Fehler: {e}")
        return False

def check_freigabe_requests_async():
    global reported_requests, last_check_time

    try:
        if not notion_client:
            logger.error("Notion Client nicht verfügbar")
            return

        logger.info("🔄 Notion API Abfrage gestartet...")
        response = notion_client.databases.query(database_id=REISEKOSTEN_FREIGABE_DB_ID)

        logger.info(f"✅ {len(response['results'])} Anträge gefunden")

        for page in response['results']:
            page_id = page['id']
            properties = page['properties']

            status = properties.get('Status', {}).get('status', {}).get('name', '') if 'Status' in properties else ''
            email = properties.get('E-Mail', {}).get('string', '') if 'E-Mail' in properties else ''
            antrag_name = ''
            betrag = properties.get('erwarteter Betrag (...)', {}).get('number', 'N/A') if 'erwarteter Betrag (...)' in properties else 'N/A'
            reise_anlass = properties.get('Reise / Anla...', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '') if 'Reise / Anla...' in properties else ''
            vorgang_id = properties.get('Vorgangs-ID', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '') if 'Vorgangs-ID' in properties else ''

            if 'Antrag' in properties and properties['Antrag'].get('title'):
                title_list = properties['Antrag']['title']
                if title_list:
                    antrag_name = title_list[0].get('text', {}).get('content', 'Unbekannt')

            logger.info(f"Seite {page_id}: Status='{status}', Email='{email}', Antrag='{antrag_name}'")

            is_new = page_id not in reported_requests
            is_status_change = page_id in reported_requests and reported_requests[page_id]['status'] != status

            if not reported_requests.get(page_id):
                reported_requests[page_id] = {"status": status, "notified_dm": False, "notified_channel": False}
            else:
                reported_requests[page_id]["status"] = status

            # 1. CHANNEL NOTIFICATION nur für neue Anträge (einmalig)
            if is_new and antrag_name and not reported_requests[page_id].get("notified_channel"):
                channel_msg = f"📝 *Neuer Antrag in Reisekosten-Freigabe*\n{antrag_name}\n💶 {betrag} EUR | 🗺️ {reise_anlass}\n🔗 https://www.notion.so/{page_id}"
                if send_slack_channel_message(channel_msg):
                    reported_requests[page_id]["notified_channel"] = True
                    logger.info(f"✅ Channel Notification: {antrag_name}")

            # 2. DM für Status-Änderungen (Freigegeben/Abgelehnt)
            if (is_status_change or is_new) and status and email:
                if status == "Freigegeben" and not reported_requests[page_id].get("notified_dm"):
                    message = f"✅ Dein Reisekostenantrag *{antrag_name}* ({vorgang_id}) wurde **freigegeben**.\n💶 {betrag} EUR\n🔗 https://www.notion.so/{page_id}"
                    if send_slack_dm(email, message):
                        reported_requests[page_id]["notified_dm"] = True
                        logger.info(f"✅ Freigabe DM: {antrag_name}")

                elif status == "Abgelehnt" and not reported_requests[page_id].get("notified_dm"):
                    message = f"❌ Dein Reisekostenantrag *{antrag_name}* ({vorgang_id}) wurde **abgelehnt**.\n🔗 https://www.notion.so/{page_id}"
                    if send_slack_dm(email, message):
                        reported_requests[page_id]["notified_dm"] = True
                        logger.info(f"✅ Ablehnung DM: {antrag_name}")

        last_check_time = datetime.now(timezone.utc).isoformat()
        logger.info(f"✅ Check abgeschlossen. {len(reported_requests)} Anträge im State")

    except Exception as e:
        logger.error(f"Fehler beim Notion Polling: {e}")

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clients": {"slack": bool(slack_client), "notion": bool(notion_client)},
        "polling": {"last_check": last_check_time, "tracked_requests": len(reported_requests)}
    }), 200

@app.route("/scheduled/check-all", methods=["POST"])
def check_all_endpoint():
    try:
        logger.info("🔄 /scheduled/check-all triggered")
        thread = threading.Thread(target=check_freigabe_requests_async, daemon=True)
        thread.start()
        return jsonify({"success": True, "message": "Polling gestartet"}), 200
    except Exception as e:
        logger.error(f"Fehler: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
