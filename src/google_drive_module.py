#!/usr/bin/env python3
"""
Google Cloud Storage Module (ehemals Google Drive Module)
Google Cloud Storage Integration für Datei-Upload
Service Account hat bereits Permissions auf den GCS Bucket
"""

import logging
import requests
from typing import Optional
from google.cloud import storage
import tempfile
import os

from config import GCS_BUCKET_NAME

logger = logging.getLogger(__name__)

def get_drive_service():
    """
    Dummy-Funktion für Rückwärtskompatibilität
    Gibt None zurück, da wir jetzt GCS verwenden
    """
    logger.info("=" * 80)
    logger.info("GOOGLE CLOUD STORAGE INITIALIZATION")
    logger.info("=" * 80)
    logger.info(f"✅ GCS Bucket: {GCS_BUCKET_NAME}")
    logger.info("✅ Service Account hat Permissions auf GCS")
    logger.info("=" * 80)
    return None  # Kompatibilität mit polling_receipts.py (check: if drive_service)

def upload_file_from_url(
    drive_service,  # Kompatibilität, wird nicht verwendet
    file_url: str,
    file_name: str,
    folder_id: str = None  # Kompatibilität, wird nicht verwendet
) -> Optional[str]:
    """
    Lädt eine Datei von einer URL zu Google Cloud Storage hoch
    Gibt GCS-Pfad zurück oder None bei Fehler

    GCS-Pfad: gs://bucket-name/rechnungen/file_name
    """
    try:
        if not file_url:
            logger.warning("File URL ist leer")
            return None

        # Datei von URL downloaden
        logger.info(f"Downloading file from Notion: {file_url}")
        response = requests.get(file_url, timeout=30)
        response.raise_for_status()
        logger.debug(f"✅ Datei heruntergeladen: {len(response.content)} bytes")

        # Temporäre Datei erstellen
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as tmp_file:
            tmp_file.write(response.content)
            tmp_path = tmp_file.name

        try:
            # Google Cloud Storage Client initialisieren
            # Nutzt Application Default Credentials (Service Account)
            storage_client = storage.Client()
            bucket = storage_client.bucket(GCS_BUCKET_NAME)

            # GCS-Pfad: rechnungen/filename
            gcs_path = f"rechnungen/{file_name}"
            blob = bucket.blob(gcs_path)

            logger.info(f"📤 Uploading zu GCS: {gcs_path}")

            # Upload zur GCS
            blob.upload_from_filename(tmp_path)

            logger.info(f"✅ Datei zu Google Cloud Storage hochgeladen: {file_name}")
            logger.info(f"   GCS-Pfad: gs://{GCS_BUCKET_NAME}/{gcs_path}")

            # Rückgabe des GCS-Pfads statt Drive-ID
            return f"gs://{GCS_BUCKET_NAME}/{gcs_path}"

        finally:
            # Temporäre Datei löschen
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                logger.debug(f"Temporäre Datei gelöscht: {tmp_path}")

    except requests.RequestException as e:
        logger.error(f"Fehler beim Download von Notion: {e}")
        return None
    except Exception as e:
        logger.error(f"Fehler beim GCS-Upload: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
