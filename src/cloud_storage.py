#!/usr/bin/env python3
"""
Cloud Storage Module
State Management für reported_requests
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict

try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    storage = None

from config import GCS_BUCKET_NAME, GCS_STATE_FILE

logger = logging.getLogger(__name__)

def load_reported_requests() -> Dict[str, str]:
    """Lade gemeldete Anfragen aus Cloud Storage"""
    if not GCS_AVAILABLE:
        logger.warning("Google Cloud Storage nicht verfügbar, verwende RAM-Only State")
        return {}

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(GCS_STATE_FILE)

        if blob.exists():
            content = blob.download_as_string()
            data = json.loads(content)
            reported_requests = data.get("reported_requests", {})

            # Sicherheit: stelle sicher, dass es ein Dict ist (nicht eine alte Liste)
            if not isinstance(reported_requests, dict):
                logger.warning(f"⚠️ Cloud Storage hat keine Dict, sondern {type(reported_requests)}. Konvertiere zu Dict.")
                return {}

            logger.info(f"✅ {len(reported_requests)} Anfragen aus Cloud Storage geladen")
            return reported_requests
        else:
            logger.info("Keine gespeicherten Anfragen gefunden, starte mit leerer Liste")
            return {}

    except Exception as e:
        logger.error(f"Fehler beim Laden aus Cloud Storage: {e}")
        return {}

def save_reported_requests(reported_dict: Dict[str, str]):
    """Speichere gemeldete Anfragen in Cloud Storage"""
    if not GCS_AVAILABLE:
        logger.warning("Google Cloud Storage nicht verfügbar, Speichern übersprungen")
        return

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(GCS_STATE_FILE)

        data = {
            "reported_requests": reported_dict,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }
        blob.upload_from_string(
            json.dumps(data, indent=2),
            content_type="application/json"
        )
        logger.info(f"✅ {len(reported_dict)} Anfragen in Cloud Storage gespeichert")

    except Exception as e:
        logger.error(f"Fehler beim Speichern in Cloud Storage: {e}")
