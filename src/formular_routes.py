"""
Reisekosten-Formular Routes
============================
Ergänzt reisekosten_backend.py um einen webbasierten Formular-Endpunkt.

Integration in src/reisekosten_backend.py (2 Zeilen nach app = Flask(__name__)):
    from formular_routes import formular_bp
    app.register_blueprint(formular_bp)

Endpunkte:
  GET  /formular          → HTML-Formular
  GET  /api/antraege      → Nur offene, freigegebene Anträge
  GET  /api/mitglieder    → Notion Workspace-Mitglieder
  POST /api/einreichung   → PDF → GCS rechnungen/ → (Cloud Function → Drive)
                            Eintrag → Notion Rechnungsdatenbank

Nutzt ausschließlich bestehende Infrastruktur:
  - google_drive_module.upload_file_from_url() → GCS Upload
  - config.py Variablen (GCS_BUCKET_NAME, REISEKOSTEN_RECHNUNG_DB_ID)
  - Application Default Credentials (wie restlicher Bot)
  - Notion Token aus NOTION_SERVICE_ACCOUNT_JSON
"""

import io
import json
import logging
import os
import tempfile

from flask import Blueprint, render_template, request, jsonify

# Interne Bot-Module
from config import (
    GCS_BUCKET_NAME,
    REISEKOSTEN_FREIGABE_DB_ID,
    REISEKOSTEN_RECHNUNG_DB_ID,
)
from notion_client_module import get_notion_client

try:
    from google.cloud import storage as gcs
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False

logger = logging.getLogger(__name__)

formular_bp = Blueprint("formular", __name__, template_folder="../templates")

# Notion Client — gleiche Instanz wie restlicher Bot
_notion = get_notion_client()


# ── GCS Upload (Bytes) ────────────────────────────────────────────────────────

def upload_bytes_to_gcs(file_bytes: bytes, filename: str) -> str:
    """
    Lädt Bytes direkt in GCS unter rechnungen/<filename> hoch.
    Die bestehende Cloud Function synct danach automatisch nach Google Drive.
    Gibt den GCS-Pfad zurück: gs://bucket/rechnungen/filename
    """
    if not GCS_AVAILABLE:
        raise RuntimeError("google-cloud-storage nicht installiert")

    storage_client = gcs.Client()
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    gcs_path = f"rechnungen/{filename}"
    blob = bucket.blob(gcs_path)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        blob.upload_from_filename(tmp_path, content_type="application/pdf")
    finally:
        os.unlink(tmp_path)

    logger.info(f"✅ PDF in GCS hochgeladen: gs://{GCS_BUCKET_NAME}/{gcs_path}")
    return f"gs://{GCS_BUCKET_NAME}/{gcs_path}"


# ── Notion Hilfsfunktionen ────────────────────────────────────────────────────

def notion_list_users() -> list:
    """Alle Notion Workspace-Mitglieder (type=person), paginiert."""
    users   = []
    cursor  = None

    while True:
        kwargs = {"page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor

        resp = _notion.users.list(**kwargs)

        for u in resp.get("results", []):
            if u.get("type") == "person":
                users.append({
                    "id":    u["id"],
                    "name":  u.get("name", ""),
                    "email": u.get("person", {}).get("email", ""),
                })

        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")

    users.sort(key=lambda u: u["name"].lower())
    return users


def notion_query_antraege() -> list:
    """Nur Anträge mit Status=Freigegeben und leerer Rechnung-Relation."""
    resp = _notion.databases.query(
        database_id=REISEKOSTEN_FREIGABE_DB_ID,
        filter={
            "and": [
                {"property": "Status",   "status":   {"equals":  "Freigegeben"}},
                {"property": "Rechnung", "relation": {"is_empty": True}},
            ]
        },
        sorts=[{"property": "Reisedatum Beginn", "direction": "descending"}],
    )

    antraege = []
    for page in resp.get("results", []):
        p = page.get("properties", {})

        vorgang_id = p.get("Vorgang-ID", {}).get("formula", {}).get("string", "")
        titel_arr  = p.get("Antrag", {}).get("title", [])
        titel      = titel_arr[0].get("plain_text", "") if titel_arr else ""
        anlass_arr = p.get("Reise / Anlass", {}).get("rich_text", [])
        anlass     = anlass_arr[0].get("plain_text", "") if anlass_arr else ""
        betrag     = p.get("erwarteter Betrag (EUR)", {}).get("number") or 0
        datum      = (p.get("Reisedatum Beginn", {}).get("date") or {}).get("start", "")

        antraege.append({
            "id":         page["id"],
            "vorgang_id": vorgang_id,
            "titel":      titel or anlass or vorgang_id,
            "anlass":     anlass,
            "betrag":     betrag,
            "datum":      datum,
        })

    return antraege


def notion_check_already_billed(antrag_ids: list) -> list:
    """Gibt Liste der Vorgang-IDs zurück, die bereits abgerechnet sind."""
    already = []
    for aid in antrag_ids:
        try:
            page     = _notion.pages.retrieve(page_id=aid)
            rechnung = page.get("properties", {}).get("Rechnung", {}).get("relation", [])
            if rechnung:
                vid = (page["properties"].get("Vorgang-ID", {})
                       .get("formula", {}).get("string", aid))
                already.append(vid)
        except Exception:
            pass
    return already


def notion_create_einreichung(
    titel:           str,
    summe:           float,
    antrag_ids:      list,
    einreicher_id:   str,
    gcs_path:        str,
    aufschluesselung: str,
) -> dict:
    """Neuen Eintrag in Rechnungsdatenbank anlegen."""
    filename = gcs_path.split("/")[-1]

    properties = {
        "Rechnung Titel": {
            "title": [{"text": {"content": titel}}]
        },
        "Summe (EUR)": {
            "number": float(summe)
        },
        "Enthaltene Anträge": {
            "relation": [{"id": aid} for aid in antrag_ids]
        },
        "Name des Einreichers": {
            "people": [{"id": einreicher_id}]
        },
        "Status": {
            "select": {"name": "Eingereicht"}
        },
        # GCS-Pfad als externe URL — Drive-Link folgt automatisch nach Cloud Function
        "Rechnungs-PDF": {
            "files": [{
                "name":     filename,
                "type":     "external",
                "external": {"url": f"https://storage.cloud.google.com/{GCS_BUCKET_NAME}/rechnungen/{filename}"}
            }]
        },
    }

    if aufschluesselung:
        properties["Aufschlüsselung tatsächliche Beträge"] = {
            "rich_text": [{"text": {"content": aufschluesselung}}]
        }

    # Rechnung erstellen
    rechnung_page = _notion.pages.create(
        parent={"database_id": REISEKOSTEN_RECHNUNG_DB_ID},
        properties=properties,
    )
    rechnung_id = rechnung_page["id"]

    # Rückrelation auf jedem Antrag setzen (Notion synct nicht automatisch)
    for aid in antrag_ids:
        try:
            antrag = _notion.pages.retrieve(page_id=aid)
            existing = antrag.get("properties", {}).get("Rechnung", {}).get("relation", [])
            existing_ids = [r["id"] for r in existing]
            if rechnung_id not in existing_ids:
                _notion.pages.update(
                    page_id=aid,
                    properties={
                        "Rechnung": {
                            "relation": existing + [{"id": rechnung_id}]
                        }
                    }
                )
                logger.info(f"✅ Rückrelation gesetzt: Antrag {aid} → Rechnung {rechnung_id}")
        except Exception as e:
            logger.warning(f"⚠️ Rückrelation fehlgeschlagen für Antrag {aid}: {e}")

    return rechnung_page


# ── Endpunkte ─────────────────────────────────────────────────────────────────

@formular_bp.route("/formular")
def formular():
    return render_template("formular.html")


@formular_bp.route("/api/mitglieder")
def get_mitglieder():
    try:
        users = notion_list_users()
        return jsonify({"mitglieder": users, "count": len(users)})
    except Exception as e:
        logger.error(f"Fehler Mitglieder: {e}")
        return jsonify({"error": str(e)}), 500


@formular_bp.route("/api/antraege")
def get_antraege():
    try:
        antraege = notion_query_antraege()
        return jsonify({"antraege": antraege, "count": len(antraege)})
    except Exception as e:
        logger.error(f"Fehler Anträge: {e}")
        return jsonify({"error": str(e)}), 500


@formular_bp.route("/api/einreichung", methods=["POST"])
def einreichung():
    """
    Multipart-Form:
      rechnung_titel    str   Pflicht
      summe             float Pflicht
      antrag_ids        str   Pflicht  – JSON-Array: '["id1","id2"]'
      einreicher_id     str   Pflicht  – Notion User-ID
      aufschluesselung  str   Optional
      rechnung_pdf      file  Pflicht  – PDF
    """
    try:
        # ── Felder ───────────────────────────────────────────────────────────
        titel            = request.form.get("rechnung_titel", "").strip()
        summe_raw        = request.form.get("summe", "")
        antrag_ids_raw   = request.form.get("antrag_ids", "[]")
        einreicher_id    = request.form.get("einreicher_id", "").strip()
        aufschluesselung = request.form.get("aufschluesselung", "").strip()
        pdf_file         = request.files.get("rechnung_pdf")

        # ── Validierung ───────────────────────────────────────────────────────
        errors = []
        if not titel:         errors.append("Titel fehlt")
        if not summe_raw:     errors.append("Summe fehlt")
        if not einreicher_id: errors.append("Einreicher fehlt")
        if not pdf_file:      errors.append("PDF fehlt")

        try:
            antrag_ids = json.loads(antrag_ids_raw)
        except Exception:
            antrag_ids = []
        if not antrag_ids:    errors.append("Mindestens ein Antrag erforderlich")

        try:
            summe = float(summe_raw)
        except ValueError:
            errors.append("Ungültige Summe")
            summe = 0.0

        if errors:
            return jsonify({"error": " | ".join(errors)}), 400

        # PDF-Validierung
        if pdf_file.content_type not in ("application/pdf",) and \
           not pdf_file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "Nur PDF-Dateien erlaubt"}), 400

        pdf_bytes = pdf_file.read()
        if len(pdf_bytes) > 20 * 1024 * 1024:
            return jsonify({"error": "PDF zu groß (max. 20 MB)"}), 400

        # ── Doppelabrechnung prüfen ───────────────────────────────────────────
        already = notion_check_already_billed(antrag_ids)
        if already:
            return jsonify({
                "error": f"Bereits abgerechnet: {', '.join(already)}. Nur offene Anträge einreichen."
            }), 409

        # ── PDF → GCS (Cloud Function synct → Drive) ──────────────────────────
        safe_name = titel.replace("/", "-").replace(" ", "_")
        filename  = f"Rechnung_{safe_name}.pdf"
        gcs_path  = upload_bytes_to_gcs(pdf_bytes, filename)

        # ── Notion-Eintrag anlegen ────────────────────────────────────────────
        result = notion_create_einreichung(
            titel=titel,
            summe=summe,
            antrag_ids=antrag_ids,
            einreicher_id=einreicher_id,
            gcs_path=gcs_path,
            aufschluesselung=aufschluesselung,
        )

        logger.info(f"✅ Einreichung erstellt: {result['id']}")
        return jsonify({
            "success":        True,
            "notion_page_id": result["id"],
            "notion_url":     result.get("url", ""),
            "gcs_path":       gcs_path,
        })

    except Exception as e:
        logger.error(f"Einreichung fehlgeschlagen: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
