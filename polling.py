#!/usr/bin/env python3
"""
Polling Module
Notion API Polling Logic
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from notion_client_module import NotionClient, APIResponseError
from config import REISEKOSTEN_FREIGABE_DB_ID
from cloud_storage import load_reported_requests, save_reported_requests
from slack_client_module import SlackClient, send_slack_dm

logger = logging.getLogger(__name__)

def check_freigabe_requests_async(
    notion_client: Optional[NotionClient],
    slack_client: Optional[SlackClient],
    slack_channel_id: str
) -> tuple[int, str, Optional[str]]:
    """
    Pollt Notion API
    Gibt zurück: (count, timestamp, error_message)
    """
    logger.info("=" * 80)
    logger.info("NOTION API POLLING GESTARTET")
    logger.info("=" * 80)

    # Lade aktuelle reported_requests aus Cloud Storage
    reported_requests = load_reported_requests()

    # Sicherheit: stelle sicher, dass reported_requests ein Dict ist
    if not isinstance(reported_requests, dict):
        logger.warning(f"⚠️ reported_requests ist nicht vom Typ Dict. Reset zu leerem Dict.")
        reported_requests = {}

    logger.info(f"Geladene reported_requests: {len(reported_requests)} Einträge")

    # Zähler für neue Anträge
    new_requests_count = 0

    try:
        if not notion_client:
            msg = "Notion Client nicht verfügbar"
            logger.error(msg)
            return 0, datetime.now(timezone.utc).isoformat(), msg

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
                # Extrahiere Properties mit robustem Error-Handling
                # Status
                status = ''
                status_prop = properties.get('Status', {})
                if isinstance(status_prop, dict):
                    status_data = status_prop.get('status', {})
                    if isinstance(status_data, dict):
                        status = status_data.get('name', '')
                    if not status:
                        status_data = status_prop.get('select', {})
                        if isinstance(status_data, dict):
                            status = status_data.get('name', '')

                # E-Mail
                email = ''
                email_prop = properties.get('E-Mail', {})
                if isinstance(email_prop, dict):
                    formula_data = email_prop.get('formula', {})
                    if isinstance(formula_data, dict):
                        email = formula_data.get('string', '')

                # Title ist eine Liste von Rich Text Objects
                antrag_name = 'Unbekannt'
                antrag_prop = properties.get('Antrag', {})
                if isinstance(antrag_prop, dict):
                    antrag_title_prop = antrag_prop.get('title', [])
                    if isinstance(antrag_title_prop, list) and len(antrag_title_prop) > 0:
                        title_obj = antrag_title_prop[0]
                        if isinstance(title_obj, dict):
                            text_obj = title_obj.get('text', {})
                            if isinstance(text_obj, dict):
                                antrag_name = text_obj.get('content', 'Unbekannt')

                # Vorgangs-ID ist eine Rich Text Liste
                vorgangs_id = ''
                vorgangs_prop = properties.get('Vorgangs-ID', {})
                if isinstance(vorgangs_prop, dict):
                    vorgangs_id_prop = vorgangs_prop.get('rich_text', [])
                    if isinstance(vorgangs_id_prop, list) and len(vorgangs_id_prop) > 0:
                        vorgangs_obj = vorgangs_id_prop[0]
                        if isinstance(vorgangs_obj, dict):
                            text_obj = vorgangs_obj.get('text', {})
                            if isinstance(text_obj, dict):
                                vorgangs_id = text_obj.get('content', '')

                # Betrag
                betrag = 'N/A'
                betrag_prop = properties.get('erwarteter Betrag (EUR)', {})
                if isinstance(betrag_prop, dict):
                    betrag_val = betrag_prop.get('number')
                    if betrag_val is not None:
                        betrag = betrag_val

                logger.debug(f"Seite {page_id}: Status={status}, Email={email}, Antrag={antrag_name}")

                # Prüfe: Ist dieser Antrag neu ODER hat der Status sich geändert?
                last_notified_status = reported_requests.get(page_id)

                if status and status != last_notified_status:
                    new_requests_count += 1
                    is_new = page_id not in reported_requests
                    logger.debug(f"✅ Antrag-Update erkannt: {antrag_name} (Status: {status}, War: {last_notified_status or 'neu'})")

                    # Neue Anträge: Status = "Eingereicht" → Channel-Nachricht
                    if status == "Eingereicht" and is_new and email:
                        channel_msg = f"📝 *Reisekostenantrag* zu {vorgangs_id} | Antragsteller:in: {email} | Betrag: {betrag} EUR\n🔗 https://www.notion.so/{page_id}"
                        try:
                            slack_client.chat_postMessage(
                                channel=slack_channel_id,
                                text=channel_msg
                            )
                            logger.info(f"✅ Neue Antrag notifiziert im Channel: {antrag_name}")
                        except Exception as slack_err:
                            logger.error(f"Fehler beim Channel-Post: {slack_err}")

                    # Freigegeben: DM an Antragsteller (egal ob neu oder Status-Update)
                    elif status == "Freigegeben" and email:
                        message = f"✅ Dein Reisekostenantrag *{antrag_name}* zu {vorgangs_id} wurde **freigegeben**. | Betrag: {betrag} EUR\n🔗 https://www.notion.so/{page_id}"
                        if send_slack_dm(slack_client, email, message):
                            logger.info(f"✅ Freigabe notifiziert: {antrag_name}")

                    # Abgelehnt: DM an Antragsteller (egal ob neu oder Status-Update)
                    elif status == "Abgelehnt" and email:
                        message = f"❌ Dein Reisekostenantrag *{antrag_name}* zu {vorgangs_id} wurde **abgelehnt**.\n🔗 https://www.notion.so/{page_id}"
                        if send_slack_dm(slack_client, email, message):
                            logger.info(f"✅ Ablehnung notifiziert: {antrag_name}")

                    # Markiere aktuellen Status als berichtet NACH Verarbeitung
                    reported_requests[page_id] = status
                    save_reported_requests(reported_requests)

                else:
                    # Alte Einträge: Status hat sich nicht geändert
                    if status in ["Eingereicht", "Freigegeben", "Abgelehnt"]:
                        logger.debug(f"⏭️ Überspringe bereits berichteten Antrag: {antrag_name} (Status: {status})")

            except Exception as page_error:
                logger.error(f"Fehler bei Verarbeitung von Seite {page_id}: {page_error}")
                continue

        timestamp = datetime.now(timezone.utc).isoformat()
        logger.info(f"✅ Polling abgeschlossen: {new_requests_count} Antrags-Updates verarbeitet, {len(reported_requests)} insgesamt erfasst")
        logger.info("=" * 80)

        return new_requests_count, timestamp, None

    except APIResponseError as e:
        msg = f"Notion API Fehler: {e.status} - {e.body}"
        logger.error(msg)
        return 0, datetime.now(timezone.utc).isoformat(), msg

    except Exception as e:
        msg = f"Unerwarteter Fehler beim Polling: {e}"
        logger.error(msg)
        logger.error(f"Fehlertyp: {type(e).__name__}")
        return 0, datetime.now(timezone.utc).isoformat(), msg
