#!/usr/bin/env python3
"""
Entry point für Google Cloud Run
Importiert die Flask App aus reisekosten-backend.py
"""

from reisekosten_backend import app

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
