#!/usr/bin/env python3
"""
Entry Point für Cloud Run
Importiert die komplette App aus reisekosten-backend.py
"""

from reisekosten_backend import app
import os

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
