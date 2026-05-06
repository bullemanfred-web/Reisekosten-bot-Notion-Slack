# Reisekosten-Workflow Backend v3

## Übersicht

Poll-basierte Notification Engine für Reisekostenantrag-Verwaltung. Integriert Notion (Datenbank), Slack (Notifications), und Google Cloud Storage (State Persistence).

## Architektur

```
main.py                          Entry Point (Cloud Run)
    ↓
reisekosten_backend.py           Flask App + Endpoints
    ├── /health                  Health Check
    └── /scheduled/check-all     Cloud Scheduler Trigger (60 min)
        ↓
    polling.py                   Polling Logic
        ├── notion_client_module Notion API Client
        ├── slack_client_module  Slack Integration
        └── cloud_storage.py     State Management
```

## Module

### `config.py`
Zentrale Konfiguration — alle Environment Variables und Konstanten.

```python
NOTION_SERVICE_ACCOUNT_JSON  # Notion Service Account Token
SLACK_BOT_TOKEN              # Slack Bot Token
SLACK_CHANNEL_ID             # Zielkanal für neue Anträge (#reisekosten)
REISEKOSTEN_FREIGABE_DB_ID   # Notion Database ID
GCS_BUCKET_NAME              # Cloud Storage Bucket für State
```

### `notion_client_module.py`
Notion API Client Initialisierung mit Error-Handling und Logging.

**Funktion:**
- `get_notion_client()` — Erstellt authenticated Notion Client

### `slack_client_module.py`
Slack SDK Wrapper für DMs und Channel Messages.

**Funktionen:**
- `get_slack_client()` — Erstellt authenticated Slack Client
- `send_slack_dm(client, email, message)` — Sendet DM an Benutzer

### `cloud_storage.py`
State Management für Google Cloud Storage.

**Funktionen:**
- `load_reported_requests()` — Lädt State beim Poll-Start
- `save_reported_requests(dict)` — Speichert State nach Verarbeitung

**State Format:**
```json
{
  "reported_requests": {
    "page_id_1": "Freigegeben",
    "page_id_2": "Eingereicht"
  },
  "last_updated": "2026-05-06T15:40:00Z"
}
```

### `polling.py`
Hauptlogik für Notion-Polling und Notification-Routing.

**Funktion:**
- `check_freigabe_requests_async()` — Pollt alle Requests, erkennt Status-Changes, sendet Notifications

**Notification-Routing:**
- **Neue Anfrage** (Status = "Eingereicht") → Channel-Message (#reisekosten)
- **Status geändert** (→ "Freigegeben", "Abgelehnt") → DM an Antragsteller

### `reisekosten_backend.py`
Flask App mit Cloud Scheduler Integration.

**Endpoints:**
- `GET /health` — Health Check mit Client-Status
- `POST /scheduled/check-all` — Trigger für Cloud Scheduler (Polling startet im Background Thread)

### `main.py`
Entry Point für Cloud Run. Importiert und startet Flask App.

## Deployment

```bash
# Local Development
python reisekosten_backend.py

# Cloud Run
gcloud run deploy reisekosten-bot \
  --source . \
  --runtime python311 \
  --region europe-west1 \
  --set-env-vars SLACK_BOT_TOKEN=xoxb-...,NOTION_SERVICE_ACCOUNT_JSON='{"access_token":"..."}' \
  --allow-unauthenticated
```

## Cloud Scheduler

Konfiguriere Cloud Scheduler, um alle 60 Minuten `POST /scheduled/check-all` zu triggern:

```bash
gcloud scheduler jobs create http check-reisekosten \
  --location europe-west1 \
  --schedule "*/60 * * * *" \
  --http-method POST \
  --uri https://reisekosten-bot-XXXXX.run.app/scheduled/check-all \
  --oidc-service-account-email [SERVICE-ACCOUNT]@[PROJECT].iam.gserviceaccount.com
```

## Removed Features

❌ **Webhook Endpoint** (`/webhook/notion`)
- Reason: Webhooks sind unreliable für Production (Notion häufig nicht erreichbar)
- Alternative: Polling alle 60 Minuten mit Cloud Scheduler (robust + einfach)

## State Deduplication

Der Kernel des Systems: **Dict[request_id] → last_notified_status**

```python
reported_requests = {
    "abc123": "Eingereicht",     # Wir haben notifiziert für Status "Eingereicht"
    "def456": "Freigegeben"      # Wir haben notifiziert für Status "Freigegeben"
}

# Next Poll:
# - Wenn Status gleich last_notified_status: skip
# - Wenn Status != last_notified_status: notify + update
# - Wenn Request nicht in Dict: notify + add
```

Das verhindert Duplikate und erlaubt Status-Change Detection.

## Logging

```
DEBUG    — Property Extraction Details
INFO     — Polling Start/End, Notifications Sent
ERROR    — API Failures, Configuration Issues
```

Logging Level kann in `reisekosten_backend.py` angepasst werden:
```python
logging.basicConfig(level=logging.DEBUG)  # oder INFO, ERROR
```

## Fehlerbehandlung

- **Cloud Storage nicht verfügbar** → Fallback zu RAM-only (keine Persistenz)
- **Notion API Fehler** → Logged + State wird nicht aktualisiert (Retry next poll)
- **Slack Fehler** → Logged + State wird aktualisiert (Message ging verloren, aber State zählt es)

## Development Checklist

- [ ] Alle Environment Variables gesetzt (`config.py`)
- [ ] Notion Service Account Token valide
- [ ] Slack Bot hat Channel + DM Permissions
- [ ] Cloud Storage Bucket exists
- [ ] Cloud Scheduler konfiguriert (alle 60 Min)
- [ ] Health Endpoint antwortet mit 200
