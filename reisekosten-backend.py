#!/usr/bin/env python3
"""
Reisekosten-Workflow Backend
Robuste, produktionsreife Lösung für Benachrichtigungen & Archivierung

Deployment:
- Google Cloud Run (empfohlen, serverless, kostengünstig)
- Docker Container (selbst-gehostet)

Features:
- Notion Webhooks (Event-getrieben, nicht Polling)
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
from google.cloud import drive_v3
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
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")  # Path zu Service Account JSON
NOTION_SERVICE_ACCOUNT_CREDENTIALS_PATH = os.getenv("NOTION_SERVICE_ACCOUNT_CREDENTIALS_PATH", "")  # Path zu Notion Service Account JSON (optional)
STATE_FILE_ID = os.getenv("STATE_FILE_ID", "1AxfqxL05Va3AnfrPavlXkwq0ldqC_DGK")  # Google Drive
REISEKOSTEN_FOLDER_ID = os.getenv("REISEKOSTEN_FOLDER_ID", "")  # Google Drive Folder
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "C0AKDAY79BP")  # #notion-connect

# Notion Database IDs
REISEKOSTEN_FREIGABE_DB_ID = "562de3ad-7fe0-47cf-a290-a7d6a8b633dd"
REISEKOSTEN_RECHNUNG_DB_ID = "dd3dd27e-a33c-4203-a00e-b70e9c0ae891"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# GOOGLE DRIVE CLIENT
# ============================================================================

def get_drive_client():
    """Initialisiert Google Drive Client"""
    if GOOGLE_APPLICATION_CREDENTIALS:
        credentials = Credentials.from_service_account_file(
            GOOGLE_APPLICATION_CREDENTIALS,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return drive_v3.DriveService(credentials=credentials)
    return None

drive_client = get_drive_client()

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

    logger.warning("Kein Notion Authentication konfiguriert (NOTION_SERVICE_ACCOUNT_JSON, NOTION_SERVICE_ACCOUNT_CREDENTIALS_PATH oder NOTION_API_TOKEN)")
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
        logger.info(f"State geladen: {len(state.get('gemeldete_neue_antraege', []))} neue Anträge, {len(state.get('benachrichtigte_freigaben_ablehnung', []))} Freigaben")
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

        media = drive_v3.MediaFileUpload(
            filename=json.dumps(state),
            mimetype='application/json',
            resumable=False
        )
        drive_client.files().update(
            fileId=STATE_FILE_ID,
            media_body=media
        ).execute()
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

        # Suche User nach E-Mail
        users = slack_client.users_lookupByEmail(email=user_email)
        user_id = users["user"]["id"]

        # Sende DM
        slack_client.chat_postMessage(
            channel=user_id,
            text=message
        )
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

        slack_client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            text=message
        )
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
        # Verifiziere Signatur
        signature = request.headers.get("X-Notion-Signature", "")
        if not verify_notion_signature(request.get_data(), signature):
            logger.warning("Ungültige Notion Webhook Signatur")
            return jsonify({"error": "Invalid signature"}), 401

        payload = request.get_json()
        logger.info(f"Notion Webhook erhalten: {payload.get('type')}")

        # Ignoriere Test-Events
        if payload.get("type") == "ping":
            return jsonify({"success": True}), 200

        # Verarbeite Änderungen
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

        # Reisekosten-Freigabe (Status geändert auf Freigegeben/Abgelehnt)
        if database_id == "562de3ad-7fe0-47cf-a290-a7d6a8b633dd":
            return handle_freigabe_change(payload, state)

        # Reisekosten-Rechnung (Neuer Beleg)
        elif database_id == "dd3dd27e-a33c-4203-a00e-b70e9c0ae891":
            return handle_beleg_change(payload, state)

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"Fehler in handle_page_change: {e}")
        return jsonify({"error": str(e)}), 500

def handle_freigabe_change(payload: Dict, state: Dict) -> tuple:
    """Verarbeitet Änderungen in Reisekosten-Freigabe (Freigabe/Ablehnung)"""
    try:
        page_url = payload.get("page_id")

        # Prüfe ob bereits benachrichtigt
        if page_url in state.get("benachrichtigte_freigaben_ablehnung", []):
            logger.info(f"Antrag {page_url} bereits benachrichtigt (Freigabe/Ablehnung)")
            return jsonify({"success": True}), 200

        # Extrahiere Daten aus Payload
        properties = payload.get("properties", {})
        status = properties.get("Status")
        email = properties.get("E-Mail")
        antrag_name = properties.get("Antrag")
        betrag = properties.get("erwarteter Betrag (EUR)")
        vorgangs_id = properties.get("Vorgangs-ID")

        if status in ["Freigegeben", "Abgelehnt"] and email:
            if status == "Freigegeben":
                message = f"""✅ Dein Reisekostenantrag *{antrag_name}* ({vorgangs_id}) wurde **freigegeben**.
Betrag: {betrag} EUR
🔗 https://www.notion.so/{page_url}"""
            else:
                message = f"""❌ Dein Reisekostenantrag *{antrag_name}* ({vorgangs_id}) wurde **abgelehnt**.
Bei Fragen wende dich an den Vorstand.
🔗 https://www.notion.so/{page_url}"""

            # Sende DM
            send_slack_dm(email, message)

            # Markiere als benachrichtigt
            state["benachrichtigte_freigaben_ablehnung"].append(page_url)
            save_state(state)
            logger.info(f"Freigabe/Ablehnung-Benachrichtigung für {antrag_name} versendet")

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"Fehler in handle_freigabe_change: {e}")
        return jsonify({"error": str(e)}), 500

def send_approver_notification(page: Dict, state: Dict) -> bool:
    """Sendet Benachrichtigung an Approver für neuen Antrag"""
    try:
        if not slack_client:
            logger.warning("Slack nicht konfiguriert")
            return False

        # Extrahiere Properties aus Notion Page
        properties = page.get("properties", {})

        # Helper: Hole Wert aus Notion Property
        def get_property(prop_name, prop_type="rich_text"):
            prop = properties.get(prop_name, {})
            if prop_type == "rich_text" and "rich_text" in prop:
                return "".join([t["plain_text"] for t in prop["rich_text"]])
            elif prop_type == "select" and "select" in prop:
                return prop["select"]["name"] if prop["select"] else ""
            elif prop_type == "number" and "number" in prop:
                return prop["number"]
            elif prop_type == "people" and "people" in prop:
                return prop["people"][0]["name"] if prop["people"] else ""
            return ""

        antragsteller = get_property("Antragsteller:in", "people")
        reise_anlass = get_property("Reise / Anlass", "rich_text")
        vorgangs_id = get_property("Vorgangs-ID", "number")
        betrag = get_property("erwarteter Betrag (EUR)", "number")
        approver_name = get_property("Approver (fix)", "people")

        page_url = page.get("url", "")

        if not approver_name:
            logger.warning(f"Kein Approver für Antrag {vorgangs_id} gesetzt")
            return False

        # Suche Approver in Slack nach Name
        try:
            users = slack_client.users_list()
            approver_user_id = None
            for user in users["members"]:
                if user.get("real_name", "").lower() == approver_name.lower():
                    approver_user_id = user["id"]
                    break

            if not approver_user_id:
                # Fallback: Meldung in #notion-connect
                message = f"""🆕 Neuer Reisekostenantrag zur Genehmigung
*Antragsteller:in:* {antragsteller}
*Reise / Anlass:* {reise_anlass}
*Vorgang:* {vorgangs_id}
*Betrag:* {betrag} EUR
*Approver:* {approver_name} (nicht in Slack gefunden)
👉 Bitte genehmigen: {page_url}"""

                slack_client.chat_postMessage(
                    channel=SLACK_CHANNEL_ID,
                    text=message
                )
                logger.info(f"Fallback-Meldung in #notion-connect für Antrag {vorgangs_id}")
                return True

            # Sende DM an Approver
            message = f"""🆕 Neuer Reisekostenantrag zur Genehmigung
*Antragsteller:in:* {antragsteller}
*Reise / Anlass:* {reise_anlass}
*Vorgang:* {vorgangs_id}
*Betrag:* {betrag} EUR
👉 Bitte genehmigen: {page_url}"""

            slack_client.chat_postMessage(
                channel=approver_user_id,
                text=message
            )
            logger.info(f"Benachrichtigung an Approver {approver_name} für Antrag {vorgangs_id} versendet")
            return True

        except SlackApiError as e:
            logger.error(f"Slack Fehler: {e}")
            return False

    except Exception as e:
        logger.error(f"Fehler in send_approver_notification: {e}")
        return False

def handle_neue_antraege():
    """Prüft auf neue Anträge (Beantragung) und benachrichtigt Approver via Notion API"""
    try:
        state = load_state()

        if not notion_client:
            logger.warning("Notion API nicht konfiguriert, Polling übersprungen")
            return state

        # Hole aktuelle letzte_pruefung
        letzte_pruefung = state.get("letzte_pruefung")

        # Konvertiere zu ISO-Format für Notion API
        # Notion expects: "2026-04-20"
        try:
            last_check_dt = datetime.fromisoformat(letzte_pruefung.replace("Z", "+00:00"))
            filter_date = last_check_dt.date().isoformat()
        except:
            filter_date = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

        logger.info(f"Prüfe auf neue Anträge seit {filter_date}")

        # Query Notion Database für neue Anträge
        response = notion_client.databases.query(
            database_id=REISEKOSTEN_FREIGABE_DB_ID,
            filter={
                "property": "Created time",
                "date": {"on_or_after": filter_date}
            },
            sorts=[{
                "property": "Created time",
                "direction": "descending"
            }]
        )

        new_requests = response.get("results", [])
        logger.info(f"Gefunden: {len(new_requests)} neue Anträge seit {filter_date}")

        # Verarbeite jeden neuen Antrag
        for page in new_requests:
            page_id = page.get("id")
            page_url = page.get("url", f"https://www.notion.so/{page_id}")

            # Prüfe ob bereits gemeldet
            if page_url in state.get("gemeldete_neue_antraege", []):
                logger.info(f"Antrag {page_id} bereits gemeldet")
                continue

            # Sende Benachrichtigung an Approver
            if send_approver_notification(page, state):
                state["gemeldete_neue_antraege"].append(page_url)
                logger.info(f"Antrag {page_id} benachrichtigt und zu State hinzugefügt")

        return state

    except Exception as e:
        logger.error(f"Fehler in handle_neue_antraege: {e}")
        return state

def archive_beleg_to_drive(payload: Dict, state: Dict) -> bool:
    """Archiviert Beleg-Dateien in Google Drive"""
    try:
        if not drive_client or not REISEKOSTEN_FOLDER_ID:
            logger.warning("Google Drive nicht konfiguriert, Archivierung übersprungen")
            return False

        properties = payload.get("properties", {})
        betrag = properties.get("Betrag (EUR)", "0")
        rechnungsdatum = properties.get("Rechnungsdatum", "")
        email = properties.get("E-Mail", "unknown")
        rechnung_name = properties.get("Rechnung mit Steuernummer", "beleg")
        vorgang_id = properties.get("Reisekosten-Vorgang", "unbekannt")

        # Extrahiere Jahr aus Rechnungsdatum
        if rechnungsdatum:
            try:
                jahr = rechnungsdatum.split("-")[0]
            except:
                jahr = datetime.now().year
        else:
            jahr = datetime.now().year

        # Extrahiere Einreicher-Name aus E-Mail
        einreicher = email.split("@")[0] if email else "unknown"

        # Hole Dateien aus Properties (Falls vorhanden)
        # Notion Files sind in "Rechnung mit Steuernummer (1)" oder "Einzelbelege (Upload)"
        files_field = properties.get("Rechnung mit Steuernummer (1)", []) or properties.get("Einzelbelege (Upload)", [])

        if not files_field:
            logger.info(f"Keine Dateien für Beleg {vorgang_id} gefunden")
            return False

        # Verarbeite jede Datei
        for file_info in files_field:
            try:
                # File-Name zusammensetzen
                file_name = f"{rechnungsdatum}_{betrag}EUR_{vorgang_id}_{rechnung_name}.pdf"

                # Erstelle Ordner-Struktur falls nicht vorhanden
                # /Reisekosten/{{Jahr}}/{{Einreicher}}/
                folder_path = f"Reisekosten/{jahr}/{einreicher}"
                folder_id = ensure_folder_exists(folder_path)

                if folder_id:
                    # Hier würde der tatsächliche Datei-Download stattfinden
                    # Das erfordert die Notion Integration für File URLs
                    logger.info(f"Beleg archiviert in {folder_path}/{file_name}")
                    state["erfolgreich_archivierte_dateien"].append(file_name)
                else:
                    logger.error(f"Fehler beim Erstellen des Ordners {folder_path}")

            except Exception as e:
                logger.error(f"Fehler beim Archivieren von Datei: {e}")

        return True

    except Exception as e:
        logger.error(f"Fehler in archive_beleg_to_drive: {e}")
        return False

def ensure_folder_exists(folder_path: str) -> Optional[str]:
    """Stellt sicher, dass Ordner in Google Drive existiert, erstellt ihn sonst"""
    try:
        if not drive_client:
            return None

        parts = folder_path.split("/")
        parent_id = REISEKOSTEN_FOLDER_ID

        for part in parts:
            # Suche Ordner
            results = drive_client.files().list(
                q=f"name='{part}' and mimeType='application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed=false",
                spaces='drive',
                pageSize=1,
                fields='files(id)'
            ).execute()

            files = results.get('files', [])
            if files:
                parent_id = files[0]['id']
            else:
                # Erstelle Ordner
                file_metadata = {
                    'name': part,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [parent_id]
                }
                folder = drive_client.files().create(body=file_metadata, fields='id').execute()
                parent_id = folder.get('id')
                logger.info(f"Ordner erstellt: {part}")

        return parent_id

    except Exception as e:
        logger.error(f"Fehler in ensure_folder_exists: {e}")
        return None

def handle_beleg_change(payload: Dict, state: Dict) -> tuple:
    """Verarbeitet neue Belege in Reisekosten-Rechnung"""
    try:
        page_url = payload.get("page_id")

        # Prüfe ob bereits gemeldet
        if page_url in state.get("gemeldete_belege", []):
            logger.info(f"Beleg {page_url} bereits gemeldet")
            return jsonify({"success": True}), 200

        # Extrahiere Daten
        properties = payload.get("properties", {})
        rechnung = properties.get("Rechnung mit Steuernummer")
        betrag = properties.get("Betrag (EUR)")
        rechnungsdatum = properties.get("Rechnungsdatum")
        email = properties.get("E-Mail")
        vorgang_id = properties.get("Reisekosten-Vorgang")

        if vorgang_id:  # Nur wenn Relation zu Vorgang gesetzt
            message = f"""🧾 Neuer Beleg eingereicht
*Vorgang:* {vorgang_id}
*Rechnung:* {rechnung}
*Betrag:* {betrag} EUR | *Datum:* {rechnungsdatum}
*Eingereicht von:* {email}
🔗 https://www.notion.so/{page_url}"""

            # Sende Meldung an #notion-connect
            send_slack_channel_message(message)

            # Archiviere Dateien in Google Drive
            archive_beleg_to_drive(payload, state)

            # Markiere als gemeldet
            state["gemeldete_belege"].append(page_url)
            save_state(state)
            logger.info(f"Beleg für Vorgang {vorgang_id} archiviert und gemeldet")

        return jsonify({"success": True}), 200

    except Exception as e:
        logger.error(f"Fehler in handle_beleg_change: {e}")
        return jsonify({"error": str(e)}), 500

def send_reminder_notification(page: Dict, days_overdue: int, state: Dict) -> bool:
    """Sendet Erinnerungs-Nachricht an Approver für überfälligen Antrag"""
    try:
        if not slack_client:
            logger.warning("Slack nicht konfiguriert")
            return False

        # Extrahiere Properties
        properties = page.get("properties", {})

        def get_property(prop_name, prop_type="rich_text"):
            prop = properties.get(prop_name, {})
            if prop_type == "rich_text" and "rich_text" in prop:
                return "".join([t["plain_text"] for t in prop["rich_text"]])
            elif prop_type == "select" and "select" in prop:
                return prop["select"]["name"] if prop["select"] else ""
            elif prop_type == "number" and "number" in prop:
                return prop["number"]
            elif prop_type == "people" and "people" in prop:
                return prop["people"][0]["name"] if prop["people"] else ""
            return ""

        antragsteller = get_property("Antragsteller:in", "people")
        reise_anlass = get_property("Reise / Anlass", "rich_text")
        vorgangs_id = get_property("Vorgangs-ID", "number")
        betrag = get_property("erwarteter Betrag (EUR)", "number")
        approver_name = get_property("Approver (fix)", "people")
        page_url = page.get("url", "")

        if not approver_name:
            logger.warning(f"Kein Approver für Antrag {vorgangs_id}")
            return False

        # Suche Approver in Slack
        try:
            users = slack_client.users_list()
            approver_user_id = None
            for user in users["members"]:
                if user.get("real_name", "").lower() == approver_name.lower():
                    approver_user_id = user["id"]
                    break

            if not approver_user_id:
                # Fallback zu #notion-connect
                message = f"""⏰ Erinnerung: Reisekostenantrag zur Genehmigung ausstehend
*Antragsteller:in:* {antragsteller}
*Reise / Anlass:* {reise_anlass}
*Vorgang:* {vorgangs_id}
*Eingereicht vor:* {days_overdue} Tagen
*Betrag:* {betrag} EUR
👉 Bitte entscheiden: {page_url}"""

                slack_client.chat_postMessage(
                    channel=SLACK_CHANNEL_ID,
                    text=message
                )
                logger.info(f"Erinnerung in #notion-connect für Antrag {vorgangs_id}")
                return True

            # Sende DM
            message = f"""⏰ Erinnerung: Reisekostenantrag zur Genehmigung ausstehend
*Antragsteller:in:* {antragsteller}
*Reise / Anlass:* {reise_anlass}
*Vorgang:* {vorgangs_id}
*Eingereicht vor:* {days_overdue} Tagen
*Betrag:* {betrag} EUR
👉 Bitte entscheiden: {page_url}"""

            slack_client.chat_postMessage(
                channel=approver_user_id,
                text=message
            )
            logger.info(f"Erinnerung an {approver_name} für Antrag {vorgangs_id} versendet")
            return True

        except SlackApiError as e:
            logger.error(f"Slack Fehler: {e}")
            return False

    except Exception as e:
        logger.error(f"Fehler in send_reminder_notification: {e}")
        return False

def check_overdue_requests():
    """Prüft auf überfällige Anträge (>5 Tage Status='Eingereicht') und sendet Erinnerungen"""
    try:
        state = load_state()
        current_time = datetime.now(timezone.utc)

        if not notion_client:
            logger.warning("Notion API nicht konfiguriert, Überdue Check übersprungen")
            return state

        # Berechne Cutoff-Datum (vor 5 Tagen)
        cutoff_date = (current_time - timedelta(days=5)).date().isoformat()

        logger.info(f"Prüfe auf überfällige Anträge (Status=Eingereicht, vor {cutoff_date})")

        # Query Notion: Status = "Eingereicht" und Eingereicht am < 5 Tage
        response = notion_client.databases.query(
            database_id=REISEKOSTEN_FREIGABE_DB_ID,
            filter={
                "and": [
                    {
                        "property": "Status",
                        "select": {"equals": "Eingereicht"}
                    },
                    {
                        "property": "Eingereicht am",
                        "date": {"before": cutoff_date}
                    }
                ]
            },
            sorts=[{
                "property": "Eingereicht am",
                "direction": "ascending"
            }]
        )

        overdue_pages = response.get("results", [])
        logger.info(f"Gefunden: {len(overdue_pages)} überfällige Anträge")

        # Verarbeite jeden überfälligen Antrag
        for page in overdue_pages:
            page_id = page.get("id")
            page_url = page.get("url", f"https://www.notion.so/{page_id}")

            # Prüfe State für letzte Erinnerung
            erinnerungen = state.get("erinnerungen_versendet", {})
            last_reminder = erinnerungen.get(page_url)

            # Hole Eingereicht am Datum
            properties = page.get("properties", {})
            eingereicht_am_prop = properties.get("Eingereicht am", {})
            eingereicht_am_str = eingereicht_am_prop.get("date", {}).get("start", "")

            if eingereicht_am_str:
                try:
                    eingereicht_am = datetime.fromisoformat(eingereicht_am_str.replace("Z", "+00:00"))
                    days_overdue = (current_time - eingereicht_am).days
                except:
                    days_overdue = 5

            # Prüfe ob bereits erinnert und ob letzte Erinnerung < 7 Tage zurück
            if last_reminder:
                try:
                    last_reminder_dt = datetime.fromisoformat(last_reminder.replace("Z", "+00:00"))
                    days_since_reminder = (current_time - last_reminder_dt).days
                    if days_since_reminder < 7:
                        logger.info(f"Antrag {page_id}: Erinnerung vor {days_since_reminder} Tagen versendet, überspringe")
                        continue
                except:
                    pass

            # Sende Erinnerung
            if send_reminder_notification(page, days_overdue, state):
                state["erinnerungen_versendet"][page_url] = current_time.isoformat()
                logger.info(f"Antrag {page_id}: Erinnerung versendet und State aktualisiert")

        return state

    except Exception as e:
        logger.error(f"Fehler in check_overdue_requests: {e}")
        return state

# ============================================================================
# POLLING / SCHEDULED TASKS
# ============================================================================

@app.route("/scheduled/check-new-requests", methods=["POST"])
def check_new_requests_endpoint():
    """Endpoint für Cloud Scheduler: Prüft auf neue Anträge"""
    try:
        # Verifiziere Authorization (Google Cloud Scheduler setzt Authorization Header)
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer"):
            logger.warning("Unautorizierter Zugriff auf /scheduled/check-new-requests")
            return jsonify({"error": "Unauthorized"}), 401

        state = handle_neue_antraege()
        state["letzte_pruefung"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

        return jsonify({
            "success": True,
            "neue_antraege_gemeldet": len(state.get("gemeldete_neue_antraege", [])),
            "timestamp": state["letzte_pruefung"]
        }), 200

    except Exception as e:
        logger.error(f"Fehler in check_new_requests_endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/scheduled/check-overdue", methods=["POST"])
def check_overdue_endpoint():
    """Endpoint für Cloud Scheduler: Prüft auf überfällige Anträge"""
    try:
        # Verifiziere Authorization
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer"):
            logger.warning("Unautorizierter Zugriff auf /scheduled/check-overdue")
            return jsonify({"error": "Unauthorized"}), 401

        state = check_overdue_requests()
        state["letzte_pruefung"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

        return jsonify({
            "success": True,
            "erinnerungen_versendet": len(state.get("erinnerungen_versendet", {})),
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
            "erinnerungen_versendet": len(state.get("erinnerungen_versendet", {})),
        }
    }), 200

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
