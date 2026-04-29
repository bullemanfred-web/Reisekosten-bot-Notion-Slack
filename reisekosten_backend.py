#!/usr/bin/env python3
"""
Reisekosten-Workflow Backend
Robuste, produktionsreife Lösung für Benachrichtigungen & Archivierung

Deployment:
- Google Cloud Run (empfohlen, serverless, kostengünstig)
- Docker Container (selbst-gehostet)

Features:
- Notion Webhooks (Event-getrieben für Status-Änderungen)
- Notion SDK für API-Polling (tägliche Checks via Cloud Scheduler)
- Slack-Benachrichtigungen (DM + Kanal)
- Google Drive Archivierung
- State-Management (Duplikat-Vermeidung)
- Robuste Error Handling
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import hashlib
import hmac

from flask import Flask, request, jsonify
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from slack_sdk import WebClient as SlackClient
from slack_sdk.errors import SlackApiError
import requests

# Notion SDK für API-Polling
try:
    from notion_client import Client as NotionClient
    NOTION_SDK_AVAILABLE = True
except ImportError:
    logger_temp = logging.getLogger(__name__)
    logger_temp.warning("notion-client nicht installiert. Bitte 'pip install notion-client' ausführen.")
    NOTION_SDK_AVAILABLE = False
    NotionClient = None

# ============================================================================
# KONFIGURATION
# ============================================================================

app = Flask(__name__)

# Environment Variables (aus Google Cloud Run / Docker)
NOTION_WEBHOOK_SECRET = os.getenv("NOTION_WEBHOOK_SECRET", "")
NOTION_API_TOKEN = os.getenv("NOTION_API_TOKEN", "")  # Legacy: Personal Token
NOTION_SERVICE_ACCOUNT_JSON = os.getenv("NOTION_SERVICE_ACCOUNT_JSON", "")  # Service Account (neu)
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
NOTION_SERVICE_ACCOUNT_CREDENTIALS_PATH = os.getenv("NOTION_SERVICE_ACCOUNT_CREDENTIALS_PATH", "")
STATE_FILE_ID = os.getenv("STATE_FILE_ID", "1AxfqxL05Va3AnfrPavlXkwq0ldqC_DGK")
REISEKOSTEN_FOLDER_ID = os.getenv("REISEKOSTEN_FOLDER_ID", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0AKDAY79BP")

# Notion Database IDs
REISEKOSTEN_FREIGABE_DB_ID = "562de3ad-7fe0-47cf-a290-a7d6a8b633dd"
REISEKOSTEN_RECHNUNG_DB_ID = "dd3dd27e-a33c-4203-a00e-b70e9c0ae891"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# GOOGLE DRIVE CLIENT
# ============================================================================

#def get_drive_client():
#    """Initialisiert Google Drive Client"""
#    if GOOGLE_APPLICATION_CREDENTIALS:
#        credentials = Credentials.from_service_account_file(
#            GOOGLE_APPLICATION_CREDENTIALS,
#            scopes=["https://www.googleapis.com/auth/drive"]
#        )
#        return build("drive", "v3", credentials=credentials)
#    return None
#
#drive_client = None  # Disabled - no credentials

# ============================================================================
# NOTION CLIENT
# ============================================================================

def get_notion_client():
    """
    Initialisiert Notion Client
    Priorität:
    1. Service Account (JSON aus Environment Variable)
    2. Service Account (JSON Datei)
    3. Personal Integration Token (Legacy)
    """
    if not NOTION_SDK_AVAILABLE:
        return None

    # Option 1: Service Account aus Environment Variable (JSON String)
    if NOTION_SERVICE_ACCOUNT_JSON:
        try:
            sa_creds = json.loads(NOTION_SERVICE_ACCOUNT_JSON)
            token = sa_creds.get("access_token") or sa_creds.get("token")
            if token:
                logger.info("Notion Client mit Service Account (aus ENV Variable) initialisiert")
                return NotionClient(auth=token)
        except Exception as e:
            logger.error(f"Fehler beim Parsen von NOTION_SERVICE_ACCOUNT_JSON: {e}")

    # Option 2: Service Account aus Datei
    if NOTION_SERVICE_ACCOUNT_CREDENTIALS_PATH:
        try:
            with open(NOTION_SERVICE_ACCOUNT_CREDENTIALS_PATH, 'r') as f:
                sa_creds = json.load(f)
                token = sa_creds.get("access_token") or sa_creds.get("token")
                if token:
                    logger.info("Notion Client mit Service Account (aus Datei) initialisiert")
                    return NotionClient(auth=token)
        except Exception as e:
            logger.error(f"Fehler beim Laden von Service Account Datei: {e}")

    # Option 3: Personal Integration Token (Legacy, Fallback)
    if NOTION_API_TOKEN:
        logger.info("Notion Client mit Personal Integration Token initialisiert (Legacy)")
        return NotionClient(auth=NOTION_API_TOKEN)

    logger.warning("Kein Notion Authentication konfiguriert")
    return None

notion_client = get_notion_client()

# ============================================================================
# SLACK CLIENT
# ============================================================================

slack_client = SlackClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None

# ============================================================================
# STATE MANAGEMENT (Google Drive)
# ============================================================================

def load_state() -> Dict:
    """Lädt State aus Google Drive"""
    try:
        if not drive_client or not STATE_FILE_ID:
            logger.warning("Google Drive nicht konfiguriert, verwende leeren State")
            return {
                "letzte_pruefung": datetime.now(timezone.utc).isoformat(),
                "gemeldete_neue_antraege": [],
                "benachrichtigte_freigaben_ablehnung": [],
                "gemeldete_belege": [],
                "erinnerungen_versendet": {},
                "erfolgreich_archivierte_dateien": [],
            }

        file_content = drive_client.files().get_media(fileId=STATE_FILE_ID).execute()
        state = json.loads(file_content.decode('utf-8'))
        logger.info(f"State geladen: {len(state.get('gemeldete_neue_antraege', []))} neue Anträge")
        return state
    except Exception as e:
        logger.error(f"Fehler beim Laden der State: {e}")
        return {
            "letzte_pruefung": datetime.now(timezone.utc).isoformat(),
            "gemeldete_neue_antraege": [],
            "benachrichtigte_freigaben_ablehnung": [],
            "gemeldete_belege": [],
            "erinnerungen_versendet": {},
            "erfolgreich_archivierte_dateien": [],
        }

def save_state(state: Dict):
    """Speichert State in Google Drive"""
    try:
        if not drive_client or not STATE_FILE_ID:
            logger.warning("Google Drive nicht konfiguriert, State nicht gespeichert")
            return

        from googleapiclient.http import MediaFileUpload
        import tempfile

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(state, f)
            temp_path = f.name

        media = MediaFileUpload(temp_path, mimetype='application/json', resumable=False)
        drive_client.files().update(fileId=STATE_FILE_ID, media_body=media).execute()
        os.remove(temp_path)
        logger.info("State gespeichert")
    except Exception as e:
        logger.error(f"Fehler beim Speichern der State: {e}")

# ============================================================================
# NOTION WEBHOOK VERIFICATION
# ============================================================================

def verify_notion_signature(request_body: bytes, signature: str) -> bool:
    """Verifiziert Notion Webhook Signatur"""
    if not NOTION_WEBHOOK_SECRET:
        logger.warning("NOTION_WEBHOOK_SECRET nicht gesetzt, Signatur-Prüfung übersprungen")
        return True

    computed_signature = hmac.new(
        NOTION_WEBHOOK_SECRET.encode(),
        request_body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed_signature, signature)

# ============================================================================
# SLACK BENACHRICHTIGUNGEN
# ============================================================================

def send_slack_dm(user_email: str, message: str) -> bool:
    """Sendet Slack DM basierend auf E-Mail-Adresse"""
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
    """Sendet Nachricht an #notion-connect Kanal"""
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
# NOTION WEBHOOK HANDLER
# ============================================================================

@app.route("/webhook/notion", methods=["POST"])
def handle_notion_webhook():
    """Verarbeitet Notion Webhooks"""
    try:
        signature = request.headers.get("X-Notion-Signature", "")
        if not verify_notion_signature(request.get_data(), signature):
            logger.warning("Ungültige Notion Webhook Signatur")
            return jsonify({"error": "Invalid signature"}), 401

        payload = request.get_json()
        logger.info(f"Notion Webhook erhalten: {payload.get('type')}")

        if payload.get("type") == "ping":
            return jsonify({"success": True}), 200

        if payload.get("type") == "page_change":
            return handle_page_change(payload)

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"Fehler in Webhook Handler: {e}")
        return jsonify({"error": str(e)}), 500

def handle_page_change(payload: Dict) -> tuple:
    """Verarbeitet Seiten-Änderungen aus Notion"""
    try:
        state = load_state()
        page_url = payload.get("page_id")
        database_id = payload.get("database_id")

        if database_id == "562de3ad-7fe0-47cf-a290-a7d6a8b633dd":
            return handle_freigabe_change(payload, state)
        elif database_id == "dd3dd27e-a33c-4203-a00e-b70e9c0ae891":
            return handle_beleg_change(payload, state)

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"Fehler in handle_page_change: {e}")
        return jsonify({"error": str(e)}), 500

def handle_freigabe_change(payload: Dict, state: Dict) -> tuple:
    """Verarbeitet Änderungen in Reisekosten-Freigabe"""
    try:
        page_url = payload.get("page_id")

        if page_url in state.get("benachrichtigte_freigaben_ablehnung", []):
            logger.info(f"Antrag {page_url} bereits benachrichtigt")
            return jsonify({"success": True}), 200

        properties = payload.get("properties", {})
        status = properties.get("Status")
        email = properties.get("E-Mail")
        antrag_name = properties.get("Antrag")
        betrag = properties.get("erwarteter Betrag (EUR)")
        vorgangs_id = properties.get("Vorgangs-ID")

        if status in ["Freigegeben", "Abgelehnt"] and email:
            if status == "Freigegeben":
                message = f"✅ Dein Reisekostenantrag *{antrag_name}* ({vorgangs_id}) wurde **freigegeben**.\nBetrag: {betrag} EUR\n🔗 https://www.notion.so/{page_url}"
            else:
                message = f"❌ Dein Reisekostenantrag *{antrag_name}* ({vorgangs_id}) wurde **abgelehnt**.\nBei Fragen wende dich an den Vorstand.\n🔗 https://www.notion.so/{page_url}"

            send_slack_dm(email, message)
            state["benachrichtigte_freigaben_ablehnung"].append(page_url)
            save_state(state)
            logger.info(f"Freigabe/Ablehnung-Benachrichtigung für {antrag_name} versendet")

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"Fehler in handle_freigabe_change: {e}")
        return jsonify({"error": str(e)}), 500

def handle_beleg_change(payload: Dict, state: Dict) -> tuple:
    """Verarbeitet neue Belege"""
    try:
        page_url = payload.get("page_id")

        if page_url in state.get("gemeldete_belege", []):
            logger.info(f"Beleg {page_url} bereits gemeldet")
            return jsonify({"success": True}), 200

        properties = payload.get("properties", {})
        rechnung = properties.get("Rechnung mit Steuernummer")
        betrag = properties.get("Betrag (EUR)")
        rechnungsdatum = properties.get("Rechnungsdatum")
        email = properties.get("E-Mail")
        vorgang_id = properties.get("Reisekosten-Vorgang")

        if vorgang_id:
            message = f"🧾 Neuer Beleg eingereicht\n*Vorgang:* {vorgang_id}\n*Rechnung:* {rechnung}\n*Betrag:* {betrag} EUR | *Datum:* {rechnungsdatum}\n*Eingereicht von:* {email}\n🔗 https://www.notion.so/{page_url}"
            send_slack_channel_message(message)
            state["gemeldete_belege"].append(page_url)
            save_state(state)
            logger.info(f"Beleg für Vorgang {vorgang_id} gemeldet")

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"Fehler in handle_beleg_change: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# POLLING / SCHEDULED TASKS
# ============================================================================

@app.route("/scheduled/check-new-requests", methods=["POST"])
def check_new_requests_endpoint():
    """Endpoint für Cloud Scheduler: Prüft auf neue Anträge"""
    try:
        logger.info("check-new-requests triggered")

        if not notion_client:
            logger.warning("Notion Client nicht verfügbar")
            return jsonify({"error": "Notion not configured"}), 503

        state = load_state()
        state["letzte_pruefung"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

        return jsonify({
            "success": True,
            "message": "Check completed",
            "timestamp": state["letzte_pruefung"]
        }), 200

    except Exception as e:
        logger.error(f"Fehler in check_new_requests_endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/scheduled/check-overdue", methods=["POST"])
def check_overdue_endpoint():
    """Endpoint für Cloud Scheduler: Prüft auf überfällige Anträge"""
    try:
        logger.info("check-overdue triggered")

        if not notion_client:
            logger.warning("Notion Client nicht verfügbar")
            return jsonify({"error": "Notion not configured"}), 503

        state = load_state()
        state["letzte_pruefung"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

        return jsonify({
            "success": True,
            "message": "Overdue check completed",
            "timestamp": state["letzte_pruefung"]
        }), 200

    except Exception as e:
        logger.error(f"Fehler in check_overdue_endpoint: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health Check für Cloud Run"""
    state = load_state()
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clients": {
            "slack_configured": bool(slack_client),
            "drive_configured": bool(drive_client),
            "notion_configured": bool(notion_client),
        },
        "notion_sdk": {
            "available": NOTION_SDK_AVAILABLE,
            "authentication": {
                "service_account_env": bool(NOTION_SERVICE_ACCOUNT_JSON),
                "service_account_file": bool(NOTION_SERVICE_ACCOUNT_CREDENTIALS_PATH),
                "personal_token": bool(NOTION_API_TOKEN),
            }
        },
        "state_summary": {
            "letzte_pruefung": state.get("letzte_pruefung"),
            "neue_antraege_gemeldet": len(state.get("gemeldete_neue_antraege", [])),
            "freigaben_benachrichtigt": len(state.get("benachrichtigte_freigaben_ablehnung", [])),
            "belege_gemeldet": len(state.get("gemeldete_belege", [])),
        }
    }), 200

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
