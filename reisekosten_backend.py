#!/usr/bin/env python3
"""
Reisekosten-Workflow Backend v2
Mit verbessertem Logging für Notion API Debug
"""

import os
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from flask import Flask, request, jsonify
from slack_sdk import WebClient as SlackClient
from slack_sdk.errors import SlackApiError

# Google Cloud Storage
try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    storage = None

# Notion SDK
try:
    from notion_client import Client as NotionClient
    from notion_client.errors import APIResponseError
    NOTION_SDK_AVAILABLE = True
except ImportError:
    NOTION_SDK_AVAILABLE = False
    NotionClient = None
    APIResponseError = None

app = Flask(__name__)

# Logging mit strukturiertem Format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# ENVIRONMENT VARIABLES
# ============================================================================

NOTION_SERVICE_ACCOUNT_JSON = os.getenv("NOTION_SERVICE_ACCOUNT_JSON", "")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0AKDAY79BP")

# Notion Database IDs
REISEKOSTEN_FREIGABE_DB_ID = "6884ef9fe113402e8a932079a90e85a2"
REISEKOSTEN_RECHNUNG_DB_ID = "dd3dd27e-a33c-4203-a00e-b70e9c0ae891"

# Cloud Storage
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "reisekosten-workflow-state")
GCS_STATE_FILE = "reported_requests.json"

# ============================================================================
# STATE
# ============================================================================

reported_requests: Set[str] = set()
last_check_time = None
last_error = None

# ============================================================================
# CLOUD STORAGE FUNCTIONS
# ============================================================================

def load_reported_requests() -> Set[str]:
    """Lade gemeldete Anfragen aus Cloud Storage"""
    global reported_requests

    if not GCS_AVAILABLE:
        logger.warning("Google Cloud Storage nicht verfügbar, verwende RAM-Only State")
        return set()

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(GCS_STATE_FILE)

        if blob.exists():
            content = blob.download_as_string()
            data = json.loads(content)
            reported_requests = set(data.get("reported_requests", []))
            logger.info(f"✅ {len(reported_requests)} Anfragen aus Cloud Storage geladen")
            return reported_requests
        else:
            logger.info("Keine gespeicherten Anfragen gefunden, starte mit leerer Liste")
            return set()

    except Exception as e:
        logger.error(f"Fehler beim Laden aus Cloud Storage: {e}")
        return set()

def save_reported_requests(reported_set: Set[str]):
    """Speichere gemeldete Anfragen in Cloud Storage"""
    if not GCS_AVAILABLE:
        logger.warning("Google Cloud Storage nicht verfügbar, Speichern übersprungen")
        return

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(GCS_STATE_FILE)

        data = {
            "reported_requests": list(reported_set),
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        blob.upload_from_string(
            json.dumps(data, indent=2),
            content_type="application/json"
        )
        logger.info(f"✅ {len(reported_set)} Anfragen in Cloud Storage gespeichert")

    except Exception as e:
        logger.error(f"Fehler beim Speichern in Cloud Storage: {e}")

# ============================================================================
# NOTION CLIENT INITIALIZATION
# ============================================================================

def get_notion_client():
    """Initialisiert Notion Client mit ausführlichem Logging"""
    global last_error

    logger.info("=" * 80)
    logger.info("NOTION CLIENT INITIALIZATION")
    logger.info("=" * 80)

    if not NOTION_SDK_AVAILABLE:
        msg = "notion-client nicht installiert"
        logger.error(msg)
        last_error = msg
        return None

    if not NOTION_SERVICE_ACCOUNT_JSON:
        msg = "NOTION_SERVICE_ACCOUNT_JSON Umgebungsvariable ist LEER"
        logger.error(msg)
        last_error = msg
        return None

    logger.info(f"Token länge: {len(NOTION_SERVICE_ACCOUNT_JSON)} Zeichen")

    try:
        sa_creds = json.loads(NOTION_SERVICE_ACCOUNT_JSON)
        logger.info(f"JSON geparst. Keys: {list(sa_creds.keys())}")

        token = sa_creds.get("access_token") or sa_creds.get("token")
        if not token:
            msg = f"Kein 'access_token' oder 'token' in JSON gefunden. Keys: {list(sa_creds.keys())}"
            logger.error(msg)
            last_error = msg
            return None

        logger.info(f"Token gefunden: {token[:30]}...")

        client = NotionClient(auth=token)
        logger.info("✅ Notion Client erfolgreich erstellt")

        # KEIN Test beim Start – wird beim ersten Request durchgeführt
        logger.info("=" * 80)
        return client

    except json.JSONDecodeError as e:
        msg = f"JSON Parse Fehler: {e}"
        logger.error(msg)
        last_error = msg
        return None
    except Exception as e:
        msg = f"Unerwarteter Fehler: {e}"
        logger.error(msg)
        last_error = msg
        return None

notion_client = get_notion_client()

# Lade reported_requests aus Cloud Storage beim Start
reported_requests = load_reported_requests()

# ============================================================================
# SLACK CLIENT
# ============================================================================

def get_slack_client():
    """Initialisiert Slack Client"""
    if not SLACK_BOT_TOKEN:
        logger.warning("Slack nicht konfiguriert (SLACK_BOT_TOKEN leer)")
        return None

    try:
        client = SlackClient(token=SLACK_BOT_TOKEN)
        logger.info("Slack Client initialisiert")
        return client
    except Exception as e:
        logger.error(f"Slack Client Fehler: {e}")
        return None

slack_client = get_slack_client()

# ============================================================================
# SLACK FUNCTIONS
# ============================================================================

def send_slack_dm(user_email: str, message: str) -> bool:
    """Sendet Slack DM an Benutzer"""
    try:
        if not slack_client:
            logger.warning("Slack nicht konfiguriert")
            return False

        logger.info(f"Versuche, DM an {user_email} zu senden...")
        users = slack_client.users_lookupByEmail(email=user_email)
        user_id = users["user"]["id"]
        slack_client.chat_postMessage(channel=user_id, text=message)
        logger.info(f"✅ DM versendet an {user_email} (User ID: {user_id})")
        return True

    except SlackApiError as e:
        logger.error(f"Slack API Fehler: {e.response['error']}")
        return False
    except Exception as e:
        logger.error(f"Fehler beim DM-Versand: {e}")
        return False

# ============================================================================
# NOTION POLLING (ASYNC)
# ============================================================================

def check_freigabe_requests_async():
    """
    Pollt Notion API im Background Thread
    Wird nicht blockierend ausgeführt
    """
    global reported_requests, last_check_time, last_error

    logger.info("=" * 80)
    logger.info("NOTION API POLLING GESTARTET")
    logger.info("=" * 80)

    try:
        if not notion_client:
            msg = "Notion Client nicht verfügbar"
            logger.error(msg)
            last_error = msg
            return

        logger.info(f"Abfrage: DB {REISEKOSTEN_FREIGABE_DB_ID}")

        response = notion_client.databases.query(
            database_id=REISEKOSTEN_FREIGABE_DB_ID,
            filter={
                "property": "Status",
                "status": {
                    "is_not_empty": True
                }
            }
        )

        logger.info(f"✅ Query erfolgreich: {len(response['results'])} Anträge gefunden")

        for page in response['results']:
            page_id = page['id']
            properties = page['properties']

            try:
                # Extrahiere Properties
                # Status: try both 'status' type (native Notion status) and 'select' type (fallback)
                status_prop = properties.get('Status', {})
                status = status_prop.get('status', {}).get('name', '') or status_prop.get('select', {}).get('name', '')
                # E-Mail kommt aus einer Formel, daher formula.string auslesen
                email = properties.get('E-Mail', {}).get('formula', {}).get('string', '')
                antrag_name = properties.get('Antrag', {}).get('title', [{}])[0].get('text', {}).get('content', 'Unbekannt')
                vorgangs_id = properties.get('Vorgangs-ID', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
                betrag = properties.get('erwarteter Betrag (EUR)', {}).get('number', 'N/A')

                logger.debug(f"Seite {page_id}: Status={status}, Email={email}, Antrag={antrag_name}")

                # Verarbeite nur neue Requests mit Status
                if status and email and page_id not in reported_requests:
                    if status == "Freigegeben":
                        message = f"✅ Dein Reisekostenantrag *{antrag_name}* zu {vorgangs_id} wurde **freigegeben**. | Betrag: {betrag} EUR\n🔗 https://www.notion.so/{page_id}"
                        if send_slack_dm(email, message):
                            reported_requests.add(page_id)
                            logger.info(f"✅ Freigabe notifiziert: {antrag_name}")

                    elif status == "Abgelehnt":
                        message = f"❌ Dein Reisekostenantrag *{antrag_name}* zu {vorgangs_id} wurde **abgelehnt**.\n🔗 https://www.notion.so/{page_id}"
                        if send_slack_dm(email, message):
                            reported_requests.add(page_id)
                            logger.info(f"✅ Ablehnung notifiziert: {antrag_name}")

            except Exception as page_error:
                logger.error(f"Fehler bei Verarbeitung von Seite {page_id}: {page_error}")
                continue

        last_check_time = datetime.now(timezone.utc).isoformat()
        last_error = None
        logger.info(f"✅ Polling abgeschlossen. {len(reported_requests)} Anträge gemeldet")

        # Speichere den aktualisierten State in Cloud Storage
        save_reported_requests(reported_requests)
        logger.info("=" * 80)

    except APIResponseError as e:
        msg = f"Notion API Fehler: {e.status} - {e.body}"
        logger.error(msg)
        last_error = msg

    except Exception as e:
        msg = f"Unerwarteter Fehler beim Polling: {e}"
        logger.error(msg)
        logger.error(f"Fehlertyp: {type(e).__name__}")
        last_error = msg

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health Check mit Status"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clients": {
            "slack_configured": bool(slack_client),
            "notion_configured": bool(notion_client),
        },
        "polling": {
            "last_check": last_check_time,
            "reported_requests": len(reported_requests),
            "mode": "API Polling (60 min)"
        },
        "last_error": last_error
    }), 200

@app.route("/scheduled/check-all", methods=["POST"])
def check_all_endpoint():
    """Endpoint für Cloud Scheduler (60 Minuten)"""
    try:
        logger.info("🔄 /scheduled/check-all triggered")

        # Starte Polling im Background Thread
        thread = threading.Thread(target=check_freigabe_requests_async, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "message": "Polling gestartet",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reported_count": len(reported_requests)
        }), 200

    except Exception as e:
        logger.error(f"Fehler in /check-all: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/webhook/notion", methods=["POST"])
def handle_notion_webhook():
    """Webhook Handler für neue Reisekostenantrag-Requests"""
    try:
        payload = request.get_json()
        webhook_type = payload.get('type')

        # Debug: Logge komplette Payload für Verification
        if webhook_type == "verification":
            logger.info("=" * 80)
            logger.info("NOTION WEBHOOK VERIFICATION REQUEST")
            logger.info("=" * 80)
            logger.info(f"Full Payload: {json.dumps(payload, indent=2)}")
            logger.info(f"Headers: {dict(request.headers)}")
            logger.info("=" * 80)

        logger.info(f"Notion Webhook: {webhook_type}")

        # Notion Verification Challenge
        if webhook_type == "ping":
            logger.info("✅ Ping empfangen")
            return jsonify({"success": True}), 200

        # Notion Webhook Verification (Challenge-Response)
        if webhook_type == "verification":
            challenge = payload.get('challenge')
            if not challenge:
                logger.error("❌ Kein Challenge-Token in Payload gefunden!")
                logger.error(f"Verfügbare Keys: {list(payload.keys())}")
                return jsonify({"error": "No challenge token"}), 400

            logger.info(f"✅ Challenge empfangen: {challenge}")
            response = {
                "type": "verification",
                "challenge": challenge
            }
            logger.info(f"Sende Response: {json.dumps(response)}")
            return jsonify(response), 200

        # Verarbeite neue/aktualisierte Seiten
        if webhook_type == "page_update":
            page_id = payload.get("page_id", "")
            properties = payload.get("properties", {})

            try:
                # Extrahiere Properties
                # Status: try both 'status' type (native Notion status) and 'select' type (fallback)
                status_prop = properties.get('Status', {})
                status = status_prop.get('status', {}).get('name', '') or status_prop.get('select', {}).get('name', '')
                # E-Mail kommt aus einer Formel, daher formula.string auslesen
                email = properties.get('E-Mail', {}).get('formula', {}).get('string', '')
                antrag_name = properties.get('Antrag', {}).get('title', [{}])[0].get('text', {}).get('content', '')
                vorgangs_id = properties.get('Vorgangs-ID', {}).get('rich_text', [{}])[0].get('text', {}).get('content', '')
                betrag = properties.get('erwarteter Betrag (EUR)', {}).get('number', 'N/A')

                # Prüfe ob neue Request (Status = "Eingereicht")
                if status == "Eingereicht" and email and antrag_name and slack_client:
                    logger.info(f"📝 Neue Reisekostenantrag erkannt: {antrag_name}")

                    # Sende Channel-Nachricht
                    channel_msg = f"📝 *Reisekostenantrag* zu {vorgangs_id} | Antragsteller:in: {email} | Betrag: {betrag} EUR\n🔗 https://www.notion.so/{page_id}"

                    # Poste in Channel
                    try:
                        slack_client.chat_postMessage(
                            channel=SLACK_CHANNEL_ID,
                            text=channel_msg
                        )
                        logger.info(f"✅ Channel-Nachricht versendet: {antrag_name}")
                    except Exception as slack_err:
                        logger.error(f"Fehler beim Channel-Post: {slack_err}")

            except Exception as page_error:
                logger.error(f"Fehler bei Webhook-Verarbeitung: {page_error}")

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"Webhook Fehler: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    logger.info(f"🚀 Server startet auf Port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
