#!/usr/bin/env python3
"""
Direct Poll Test
Ruft das Polling lokal auf und zeigt alle Logs
"""

import sys
import logging
from datetime import datetime, timezone

# Logging setup mit maximal Details
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

logger = logging.getLogger(__name__)

from config import SLACK_CHANNEL_ID
from notion_client_module import get_notion_client
from slack_client_module import get_slack_client
from google_drive_module import get_drive_service
from polling import check_freigabe_requests_async
from polling_receipts import check_receipt_requests_async

print("=" * 80)
print("DIRECT POLL TEST")
print("=" * 80)
print("")

# Get clients
notion_client = get_notion_client()
slack_client = get_slack_client()
drive_service = get_drive_service()

print(f"notion_client: {'✅ YES' if notion_client else '❌ NO'}")
print(f"slack_client: {'✅ YES' if slack_client else '❌ NO'}")
print(f"drive_service: {'✅ YES' if drive_service else '❌ NO'}")
print("")
print("=" * 80)
print("STARTING POLLING")
print("=" * 80)
print("")

# Test Anträge Polling
try:
    print("🔄 Running check_freigabe_requests_async...")
    count1, timestamp1, error1 = check_freigabe_requests_async(
        notion_client,
        slack_client,
        SLACK_CHANNEL_ID
    )
    print(f"✅ Anträge-Polling: {count1} updates, error: {error1}")
except Exception as e:
    print(f"❌ Anträge-Polling failed: {e}")
    import traceback
    traceback.print_exc()

print("")
print("=" * 80)
print("")

# Test Rechnungen Polling
try:
    print("🔄 Running check_receipt_requests_async...")
    count2, timestamp2, error2 = check_receipt_requests_async(
        notion_client,
        slack_client,
        SLACK_CHANNEL_ID,
        drive_service
    )
    print(f"✅ Rechnungs-Polling: {count2} updates, error: {error2}")
except Exception as e:
    print(f"❌ Rechnungs-Polling failed: {e}")
    import traceback
    traceback.print_exc()

print("")
print("=" * 80)
print("POLL COMPLETE")
print("=" * 80)
