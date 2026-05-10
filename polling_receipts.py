#!/usr/bin/env python3
"""
Polling Module für Rechnungseinreichungen
Notion API Polling Logic für Reisekosten-Rechnungseinreichung
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from notion_client_module import NotionClient, APIResponseError
from config import REISEKOSTEN_RECHNUNG_DB_ID
from cloud_storage import load_reported_requests, save_reported_requests
from slack_client_module import SlackClient, send_slack_dm
from google_drive_module import get_drive_service, upload_file_from_url
from message_templates import (
    build_new_receipt_channel_message,
    build_receipt_approval_dm_message,
    build_receipt_rejection_dm_message
)

logger = logging.getLogger(__name__)

def check_receipt_requests_async(
    notion_client: Optional[NotionClient],
    slack_client: Optional[SlackClient],
    slack_channel_id: str,
    drive_service: Optional = None,
    force_reprocess: bool = False
) -> tuple[int, str, Optional[str]]:
    """
    Pollt Notion API für Rechnungseinreichungen
    Gibt zurück: (count, timestamp, error_message)
    force_reprocess: Wenn True, werden alle Rechnungen neu verarbeitet (Debug)
    """
    logger.info("=" * 80)
    logger.info("RECHNUNGS-POLLING GESTARTET")
    if force_reprocess:
        logger.info("⚠️ DEBUG MODE: force_reprocess=True - alle Rechnungen werden neu verarbeitet")
    logger.info("=" * 80)

    # Lade aktuelle reported_receipts aus Cloud Storage
    reported_receipts = load_reported_requests() if not force_reprocess else {}

    # Sicherheit: stelle sicher, dass reported_receipts ein Dict ist
    if not isinstance(reported_receipts, dict):
        logger.warning(f"⚠️ reported_receipts ist nicht vom Typ Dict. Reset zu leerem Dict.")
        reported_receipts = {}

    logger.info(f"Geladene reported_receipts: {len(reported_receipts)} Einträge")

    # Zähler für neue Rechnungen
    new_receipts_count = 0

    try:
        if not notion_client:
            msg = "Notion Client nicht verfügbar"
            logger.error(msg)
            return 0, datetime.now(timezone.utc).isoformat(), msg

        logger.info(f"Abfrage: Rechnungs-DB {REISEKOSTEN_RECHNUNG_DB_ID}")

        response = notion_client.databases.query(
            database_id=REISEKOSTEN_RECHNUNG_DB_ID,
            filter={
                "property": "Status",
                "select": {
                    "is_not_empty": True
                }
            }
        )

        logger.info(f"✅ Query erfolgreich: {len(response['results'])} Rechnungen gefunden")

        for page in response['results']:
            page_id = page['id']
            properties = page['properties']

            try:
                # Extrahiere Properties
                # Status
                status = ''
                status_prop = properties.get('Status', {})
                if isinstance(status_prop, dict):
                    status_data = status_prop.get('select', {})
                    if isinstance(status_data, dict):
                        status = status_data.get('name', '')

                # Titel
                titel = 'Unbekannt'
                titel_prop = properties.get('Rechnung Titel', {})
                if isinstance(titel_prop, dict):
                    titel_text_list = titel_prop.get('title', [])
                    if isinstance(titel_text_list, list) and len(titel_text_list) > 0:
                        titel_obj = titel_text_list[0]
                        if isinstance(titel_obj, dict):
                            text_obj = titel_obj.get('text', {})
                            if isinstance(text_obj, dict):
                                titel = text_obj.get('content', 'Unbekannt')

                # Summe
                summe = 'N/A'
                summe_prop = properties.get('Summe (EUR)', {})
                if isinstance(summe_prop, dict):
                    summe_val = summe_prop.get('number')
                    if summe_val is not None:
                        summe = summe_val

                # E-Mail (aus Formel-Property)
                email = 'N/A'
                email_prop = properties.get('E-Mail', {})
                if isinstance(email_prop, dict):
                    formula_data = email_prop.get('formula', {})
                    if isinstance(formula_data, dict):
                        email_val = formula_data.get('string')
                        if email_val:
                            email = email_val

                # Name des Einreichers (aus Person-Property)
                einreicher_name = 'Unbekannt'
                einreicher_prop = properties.get('Name des Einreichers', {})
                if isinstance(einreicher_prop, dict):
                    people_list = einreicher_prop.get('people', [])
                    if isinstance(people_list, list) and len(people_list) > 0:
                        person_obj = people_list[0]
                        if isinstance(person_obj, dict):
                            einreicher_name = person_obj.get('name', 'Unbekannt')

                antraege_prop = properties.get('Enthaltene Anträge', {})

                # Anträge (als String)
                antraege = 'N/A'
                if isinstance(antraege_prop, dict):
                    relation_list = antraege_prop.get('relation', [])
                    if isinstance(relation_list, list) and len(relation_list) > 0:
                        antraege = f"{len(relation_list)} Antrag(e)"

                # Notizen vom Vorstand
                notizen = 'Keine Notizen'
                notizen_prop = properties.get('Notizen vorstand', {})
                if isinstance(notizen_prop, dict):
                    notizen_text_list = notizen_prop.get('rich_text', [])
                    if isinstance(notizen_text_list, list) and len(notizen_text_list) > 0:
                        notizen_obj = notizen_text_list[0]
                        if isinstance(notizen_obj, dict):
                            notizen_text = notizen_obj.get('text', {})
                            if isinstance(notizen_text, dict):
                                notizen = notizen_text.get('content', 'Keine Notizen')

                # Rechnungs-PDF (Files Property)
                pdf_urls = []
                pdf_prop = properties.get('Rechnungs-PDF', {})
                if isinstance(pdf_prop, dict):
                    files_list = pdf_prop.get('files', [])
                    if isinstance(files_list, list):
                        for file_obj in files_list:
                            if isinstance(file_obj, dict):
                                file_url = file_obj.get('file', {}).get('url') if file_obj.get('file') else None
                                if file_url:
                                    pdf_urls.append({'url': file_url, 'name': file_obj.get('name', 'Rechnung.pdf')})

                logger.debug(f"Seite {page_id}: Status={status}, Titel={titel}, Summe={summe}, PDFs={len(pdf_urls)}")

                # Prüfe: Ist diese Rechnung neu ODER hat der Status sich geändert?
                last_notified_status = reported_receipts.get(page_id)

                if status and status != last_notified_status:
                    new_receipts_count += 1
                    is_new = page_id not in reported_receipts
                    logger.debug(f"✅ Rechnung-Update erkannt: {titel} (Status: {status}, War: {last_notified_status or 'neu'})")

                    # Neue Rechnungen: Status = "Eingereicht" → Channel-Nachricht
                    if status == "Eingereicht" and is_new:
                        message_blocks = build_new_receipt_channel_message(
                            titel=titel,
                            summe=summe,
                            einreicher_name=einreicher_name,
                            antraege=antraege,
                            page_id=page_id
                        )
                        try:
                            slack_client.chat_postMessage(
                                channel=slack_channel_id,
                                **message_blocks
                            )
                            logger.info(f"✅ Neue Rechnung notifiziert im Channel: {titel}")
                        except Exception as slack_err:
                            logger.error(f"Fehler beim Channel-Post: {slack_err}")

                    # Genehmigt: DM an Einreicher + PDF zu Google Drive hochladen
                    elif status == "Genehmigt" and email and email != 'N/A':
                        message_blocks = build_receipt_approval_dm_message(
                            titel=titel,
                            summe=summe,
                            antraege=antraege,
                            page_id=page_id
                        )
                        if send_slack_dm(slack_client, email, message_blocks):
                            logger.info(f"✅ Genehmigung notifiziert: {titel}")

                        # PDFs zu Google Drive hochladen
                        logger.info(f"📊 PDF-Upload Check: pdf_urls={len(pdf_urls) if pdf_urls else 0}, drive_service={'✅ YES' if drive_service else '❌ NO'}")
                        if pdf_urls and drive_service:
                            logger.info(f"🚀 Starte PDF-Upload für {len(pdf_urls)} Datei(en)")
                            for pdf in pdf_urls:
                                try:
                                    logger.info(f"📤 Uploading: {pdf['name']} ({pdf['url']})")
                                    file_id = upload_file_from_url(
                                        drive_service,
                                        pdf['url'],
                                        pdf['name']
                                    )
                                    if file_id:
                                        logger.info(f"✅ PDF zu Google Drive hochgeladen: {pdf['name']} (ID: {file_id})")
                                    else:
                                        logger.warning(f"⚠️ PDF-Upload fehlgeschlagen: {pdf['name']}")
                                except Exception as e:
                                    logger.error(f"Fehler beim PDF-Upload: {e}")
                                    import traceback
                                    logger.error(traceback.format_exc())
                        elif pdf_urls and not drive_service:
                            logger.warning("⚠️ Google Drive Service nicht verfügbar - PDFs werden nicht hochgeladen")
                        elif not pdf_urls:
                            logger.debug(f"⚠️ Keine PDFs gefunden für Rechnung: {titel}")

                    # Abgelehnt: DM an Einreicher (egal ob neu oder Status-Update)
                    elif status == "Abgelehnt" and email and email != 'N/A':
                        message_blocks = build_receipt_rejection_dm_message(
                            titel=titel,
                            summe=summe,
                            antraege=antraege,
                            notizen=notizen,
                            page_id=page_id
                        )
                        if send_slack_dm(slack_client, email, message_blocks):
                            logger.info(f"✅ Ablehnung notifiziert: {titel}")

                    # Markiere aktuellen Status als berichtet NACH Verarbeitung
                    reported_receipts[page_id] = status
                    save_reported_requests(reported_receipts)

                else:
                    # Alte Einträge: Status hat sich nicht geändert
                    if status in ["Eingereicht", "Genehmigt", "Abgelehnt"]:
                        logger.debug(f"⏭️ Überspringe bereits berichtete Rechnung: {titel} (Status: {status})")

            except Exception as page_error:
                logger.error(f"Fehler bei Verarbeitung von Seite {page_id}: {page_error}")
                continue

        timestamp = datetime.now(timezone.utc).isoformat()
        logger.info(f"✅ Rechnungs-Polling abgeschlossen: {new_receipts_count} Updates verarbeitet, {len(reported_receipts)} insgesamt erfasst")
        logger.info("=" * 80)

        return new_receipts_count, timestamp, None

    except APIResponseError as e:
        msg = f"Notion API Fehler: {e.status} - {e.body}"
        logger.error(msg)
        return 0, datetime.now(timezone.utc).isoformat(), msg

    except Exception as e:
        msg = f"Unerwarteter Fehler beim Rechnungs-Polling: {e}"
        logger.error(msg)
        logger.error(f"Fehlertyp: {type(e).__name__}")
        return 0, datetime.now(timezone.utc).isoformat(), msg
