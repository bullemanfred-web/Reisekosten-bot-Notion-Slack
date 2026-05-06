#!/usr/bin/env python3
"""
Reisekosten-Workflow Backend v3 (Refactored)
Polling-basierte Notification Engine ohne Webhooks
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Optional

from flask import Flask, request, jsonify

from config import SLACK_CHANNEL_ID
from notion_client_module import get_notion_client
from slack_client_module import get_slack_client
from polling import check_freigabe_requests_async

app = Flask(__name__)

# Logging mit strukturiertem Format
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# STATE
# ============================================================================

notion_client = get_notion_client()
slack_client = get_slack_client()

last_check_time: Optional[str] = None
last_error: Optional[str] = None

# ============================================================================
# ENDPOINTS
# ============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health Check mit Status"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clients": {
            "slack_configured": bool(slack_client),
            "notion_configured": bool(notion_client),
        },
        "polling": {
            "last_check": last_check_time,
            "mode": "API Polling (60 min)"
        },
        "last_error": last_error
    }), 200

@app.route("/scheduled/check-all", methods=["POST"])
def check_all_endpoint():
    """Endpoint für Cloud Scheduler (60 Minuten)"""
    global last_check_time, last_error

    try:
        logger.info("🔄 /scheduled/check-all triggered")

        # Starte Polling im Background Thread
        def run_polling():
            global last_check_time, last_error
            count, timestamp, error = check_freigabe_requests_async(
                notion_client,
                slack_client,
                SLACK_CHANNEL_ID
            )
            last_check_time = timestamp
            last_error = error

        thread = threading.Thread(target=run_polling, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "message": "Polling gestartet",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200

    except Exception as e:
        logger.error(f"Fehler in /check-all: {e}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 8080))
    logger.info(f"🚀 Server startet auf Port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
