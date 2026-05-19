# Reisekosten-Workflow Backend v4

## Übersicht

Poll-basierte Notification Engine für Reisekostenantrag- und Rechnungsverwaltung. Integriert Notion (Datenbank), Slack (Notifications), Google Cloud Storage (State Persistence & PDF-Zwischenspeicher), Google Drive (PDF-Archiv) und ein HTML-Erfassungsformular.

## Architektur
templates/formular.html          Rechnungserfassung (HTML-Formular)
↓
main.py                          Entry Point (Cloud Run)
↓
reisekosten_backend.py           Flask App + Endpoints
├── /health                  Health Check
├── /formular                Rechnungserfassungsformular
├── /api/mitglieder          Notion-Mitgliederliste
├── /api/antraege            Offene Anträge
├── /api/einreichung         PDF-Upload + Notion-Eintrag
└── /scheduled/check-all    Cloud Scheduler Trigger (60 min)
├── polling.py           Antrags-Polling
└── polling_receipts.py  Rechnungs-Polling
└── cloud_storage.py State Management (getrennte Keys)

## Module

### `config.py`
Zentrale Konfiguration — alle Environment Variables und Konstanten.

```python
NOTION_SERVICE_ACCOUNT_JSON      # Notion Service Account Token
SLACK_BOT_TOKEN                  # Slack Bot Token
SLACK_CHANNEL_ID                 # Zielkanal für neue Anträge (#reisekosten)
REISEKOSTEN_FREIGABE_DB_ID       # Notion Database ID (Anträge)
REISEKOSTEN_RECHNUNG_DB_ID       # Notion Database ID (Rechnungen)
GCS_BUCKET_NAME                  # Cloud Storage Bucket (reisekosten-workflow-state)
```

### `cloud_storage.py`
State Management für Google Cloud Storage — zwei getrennte State-Keys.

**Funktionen:**
- `load_reported_requests()` — Lädt Antrags-State beim Poll-Start
- `save_reported_requests(dict)` — Speichert Antrags-State nach Verarbeitung
- `load_reported_receipts()` — Lädt Rechnungs-State beim Poll-Start
- `save_reported_receipts(dict)` — Speichert Rechnungs-State nach Verarbeitung

**State Format:**
```json
{
  "reported_requests": {
    "page_id_1": "Freigegeben",
    "page_id_2": "Eingereicht"
  },
  "reported_receipts": {
    "page_id_3": "Eingereicht",
    "page_id_4": "Genehmigt"
  },
  "last_updated": "2026-05-19T18:35:00Z"
}
```

> Wichtig: Anträge und Rechnungen nutzen getrennte State-Keys (reported_requests vs. reported_receipts) in derselben JSON-Datei. Das verhindert gegenseitiges Überschreiben bei parallelem Polling.

### `polling.py`
Polling-Logik für Reisekostenfreigabe-Anträge.

**Notification-Routing:**
- Neue Anfrage (Status = "Eingereicht") → Channel-Message (#reisekosten)
- Status geändert (→ "Freigegeben", "Abgelehnt") → DM an Antragsteller

### `polling_receipts.py`
Polling-Logik für Rechnungen.

**Notification-Routing:**
- Neue Rechnung (Status = "Eingereicht") → Channel-Message (#reisekosten)
- Status = "Genehmigt" → DM an Einreicher + PDF-Download aus Notion → Upload nach GCS → Cloud Function triggert GCS→Drive Sync

### `formular_routes.py`
Flask Blueprint für das Rechnungserfassungsformular.

**Endpoints:**
- GET /formular — Rendert HTML-Formular
- GET /api/mitglieder — Gibt Notion-Mitgliederliste zurück
- GET /api/antraege          — Gibt offene, freigegebene Anträge zurück (ohne bereits abgerechnete)
- POST /api/einreichung — Nimmt PDF entgegen, lädt in GCS hoch, erstellt Notion-Eintrag

**Dateiname-Schema:** Rechnung_<Titel>.pdf (aus Rechnungstitel generiert)

### `gcs-to-drive-sync` (Cloud Function)
Event-getriggerte Cloud Function in us-central1.
- Trigger: google.storage.object.finalize auf rechnungen/-Prefix
- Aktion: PDF von GCS → Google Drive Ordner (1wCo_3qi6QPeRDm2uLOrOBD7AylqnUGmw)
- Cleanup: Löscht PDF aus GCS nach erfolgreichem Drive-Upload

## Deployment

### Cloud Run (automatisch via GitHub Actions)
```bash
git add .
git commit -m "feat: beschreibung"
git push origin main
```

GitHub Actions: https://github.com/bullemanfred-web/Reisekosten-bot-Notion-Slack/actions

### Cloud Function (manuell)
```bash
cd /tmp/gcf
gcloud functions deploy gcs-to-drive-sync \
  --region=us-central1 \
  --runtime=python311 \
  --trigger-resource=reisekosten-workflow-state \
  --trigger-event=google.storage.object.finalize \
  --entry-point=gcs_to_drive_sync \
  --source=. \
  --memory=256MB
```

### Health Check
```bash
curl https://reisekosten-bot-20041081481.europe-west1.run.app/health | jq .
```

### Scheduler manuell triggern
```bash
gcloud scheduler jobs run check-reisekosten --location=europe-west1
```

## GCS Bucket
gs://reisekosten-workflow-state/
├── reported_requests.json      # State (Anträge + Rechnungen)
└── rechnungen/                 # Temporärer PDF-Zwischenspeicher
└── *.pdf                   # Werden nach Drive-Sync gelöscht

> Der Bucket ist öffentlich lesbar (allUsers:objectViewer) damit Notion die PDF-Links anzeigen kann.

## State Deduplication

Dict[request_id] → last_notified_status verhindert Duplikate:

- Status == last_notified_status → skip
- Status != last_notified_status → notify + update
- Request nicht im Dict → notify + add

## Fehlerbehandlung

| Szenario | Verhalten |
|----------|-----------|
| Cloud Storage nicht verfügbar | Fallback zu RAM-only |
| Notion API Fehler | Geloggt, Retry next poll |
| Slack Fehler | Geloggt, Polling läuft weiter |
| PDF Download schlägt fehl | Geloggt, weiter |

## Development Checklist

- [ ] Alle Environment Variables gesetzt
- [ ] Notion Service Account Token valide
- [ ] Slack Bot hat Channel + DM Permissions
- [ ] Cloud Storage Bucket existiert
- [ ] Cloud Scheduler konfiguriert (alle 60 Min)
- [ ] Cloud Function gcs-to-drive-sync aktiv (us-central1)
- [ ] Health Endpoint antwortet mit "status": "healthy"

**Version:** 4.0
**Letzte Aktualisierung:** 19. Mai 2026
