#!/usr/bin/env python3
"""
Google Drive Module
Google Drive API Integration für Datei-Upload
"""

import logging
import requests
from typing import Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import tempfile
import os

from config import GOOGLE_DRIVE_CREDENTIALS, GOOGLE_DRIVE_FOLDER_ID

logger = logging.getLogger(__name__)

def get_drive_service():
    """Initialisiert Google Drive Service"""
    try:
        if not GOOGLE_DRIVE_CREDENTIALS:
            logger.warning("Google Drive nicht konfiguriert (GOOGLE_DRIVE_CREDENTIALS leer)")
            return None

        credentials = service_account.Credentials.from_service_account_info(
            GOOGLE_DRIVE_CREDENTIALS,
            scopes=['https://www.googleapis.com/auth/drive']
        )

        service = build('drive', 'v3', credentials=credentials)
        logger.info("✅ Google Drive Service initialisiert")
        return service
    except Exception as e:
        logger.error(f"Google Drive Service Fehler: {e}")
        return None

def upload_file_from_url(
    drive_service,
    file_url: str,
    file_name: str,
    folder_id: str = GOOGLE_DRIVE_FOLDER_ID
) -> Optional[str]:
    """
    Lädt eine Datei von einer URL zu Google Drive hoch
    Gibt File-ID zurück oder None bei Fehler
    """
    try:
        if not drive_service:
            logger.warning("Google Drive Service nicht verfügbar")
            return None

        if not file_url:
            logger.warning("File URL ist leer")
            return None

        # Datei von URL downloaden
        logger.info(f"Downloading file from: {file_url}")
        response = requests.get(file_url, timeout=30)
        response.raise_for_status()

        # Temporäre Datei erstellen
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1]) as tmp_file:
            tmp_file.write(response.content)
            tmp_path = tmp_file.name

        try:
            # Metadaten für Upload
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }

            # Upload
            media = MediaFileUpload(tmp_path, resumable=True)
            file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            file_id = file.get('id')
            logger.info(f"✅ Datei zu Google Drive hochgeladen: {file_name} (ID: {file_id})")
            return file_id

        finally:
            # Temporäre Datei löschen
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except requests.RequestException as e:
        logger.error(f"Fehler beim Download von {file_url}: {e}")
        return None
    except HttpError as e:
        logger.error(f"Google Drive API Fehler: {e}")
        return None
    except Exception as e:
        logger.error(f"Fehler beim Upload zu Google Drive: {e}")
        return None
