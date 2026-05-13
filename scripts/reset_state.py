#!/usr/bin/env python3
"""
Reset Cloud Storage State
Löscht die reported_receipts für einen Fresh Start
"""

import logging
from cloud_storage import save_reported_requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("=" * 80)
print("CLOUD STORAGE STATE RESET")
print("=" * 80)

# Reset zu leerem Dict
reported_receipts = {}
save_reported_requests(reported_receipts)

logger.info("✅ Cloud Storage State gelöscht. Nächster Poll wird alles neu verarbeiten.")
print("=" * 80)
