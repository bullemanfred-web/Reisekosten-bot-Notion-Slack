#!/usr/bin/env python3
"""
Cloud Storage Module
State Management für reported_requests UND reported_receipts
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

def _load_full_state() -> dict:
    """Lade kompletten State aus Cloud Storage"""
    if not GCS_AVAILABLE:
        return {}
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(GCS_STATE_FILE)
        if blob.exists():
            content = blob.download_as_string()
            return json.loads(content)
        return {}
    except Exception as e:
        logger.error(f"Fehler beim Laden aus Cloud Storage: {e}")
        return {}

def _save_full_state(data: dict):
    """Speichere kompletten State in Cloud Storage"""
    if not GCS_AVAILABLE:
        logger.warning("Google Cloud Storage nicht verfügbar, Speichern übersprungen")
        return
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(GCS_STATE_FILE)
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        blob.upload_from_string(
            json.dumps(data, indent=2),
            content_type="application/json"
        )
    except Exception as e:
        logger.error(f"Fehler beim Speichern in Cloud Storage: {e}")

def load_reported_requests() -> Dict[str, str]:
    """Lade gemeldete Anträge aus Cloud Storage"""
    data = _load_full_state()
    reported = data.get("reported_requests", {})
    if not isinstance(reported, dict):
        logger.warning("⚠️ reported_requests ist kein Dict. Reset.")
        return {}
    logger.info(f"✅ {len(reported)} Anträge aus Cloud Storage geladen")
    return reported

def save_reported_requests(reported_dict: Dict[str, str]):
    """Speichere gemeldete Anträge in Cloud Storage (ohne reported_receipts zu überschreiben)"""
    data = _load_full_state()
    data["reported_requests"] = reported_dict
    _save_full_state(data)
    logger.info(f"✅ {len(reported_dict)} Anträge in Cloud Storage gespeichert")

def load_reported_receipts() -> Dict[str, str]:
    """Lade gemeldete Rechnungen aus Cloud Storage"""
    data = _load_full_state()
    reported = data.get("reported_receipts", {})
    if not isinstance(reported, dict):
        logger.warning("⚠️ reported_receipts ist kein Dict. Reset.")
        return {}
    logger.info(f"✅ {len(reported)} Rechnungen aus Cloud Storage geladen")
    return reported

def save_reported_receipts(reported_dict: Dict[str, str]):
    """Speichere gemeldete Rechnungen in Cloud Storage (ohne reported_requests zu überschreiben)"""
    data = _load_full_state()
    data["reported_receipts"] = reported_dict
    _save_full_state(data)
    logger.info(f"✅ {len(reported_dict)} Rechnungen in Cloud Storage gespeichert")
