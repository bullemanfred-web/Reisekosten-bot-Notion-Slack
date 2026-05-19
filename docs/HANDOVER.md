# Handover Documentation – Reisekosten-Bot

**Status:** Production-ready (v4)
**Last Updated:** 19. Mai 2026

## Quick Start

### Was macht das System?

1. Rechnungserfassung: HTML-Formular nimmt PDFs entgegen, speichert in GCS, legt Eintrag in Notion an
2. Polling (alle 60 Min): Prüft Notion-Datenbanken auf neue/geänderte Anträge und Rechnungen
3. Slack-Notifications: Channel-Messages (neue Einträge) und DMs (Status-Änderungen)
4. PDF-Archivierung: Genehmigte Rechnungen werden automatisch nach Google Drive synchronisiert

### Wo läuft es?

| Komponente | Details |
|-----------|---------|
| Cloud Run | reisekosten-bot, europe-west1 |
| URL | https://reisekosten-bot-20041081481.europe-west1.run.app |
| Formular | https://reisekosten-bot-20041081481.europe-west1.run.app/formular |
| Cloud Function | gcs-to-drive-sync, us-central1 |
| GCS Bucket | gs://reisekosten-workflow-state/ |
| GitHub | https://github.com/bullemanfred-web/Reisekosten-bot-Notion-Slack |

### Health Check

```bash
curl https://reisekosten-bot-20041081481.europe-west1.run.app/health | jq .
```

## Vollständiger End-to-End Flow
Einreicher → Formular ausfüllen + PDF hochladen
→ GCS Upload + Notion Eintrag
→ (60 Min Poll) → Slack Channel: Neue Rechnung
→ Genehmiger setzt Status auf Genehmigt
→ (60 Min Poll) → Slack DM an Einreicher
→ PDF: GCS → Google Drive
→ PDF aus GCS gelöscht

## Häufige Aufgaben

### System testen
```bash
curl https://reisekosten-bot-20041081481.europe-west1.run.app/health
gcloud scheduler jobs run check-reisekosten --location=europe-west1
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=reisekosten-bot" \
  --limit 20 --format json | jq '.[].jsonPayload.message // .[].textPayload' 2>/dev/null | head -30
```

### Code deployen (Cloud Run)
```bash
cd ~/Reisekosten-bot-Notion-Slack
git add .
git commit -m "feat: beschreibung"
git push origin main
```

GitHub Actions deployt automatisch.

### Cloud Function deployen
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

### State anschauen
```bash
gsutil cat gs://reisekosten-workflow-state/reported_requests.json | jq .
```

## Troubleshooting

### Slack-Notification kam doppelt
State-Keys prüfen — beide müssen vorhanden sein:
```bash
gsutil cat gs://reisekosten-workflow-state/reported_requests.json | jq 'keys'
# Erwartung: ["last_updated", "reported_receipts", "reported_requests"]
```

### PDF in Notion zeigt 403 Forbidden
```bash
gsutil iam ch allUsers:objectViewer gs://reisekosten-workflow-state/
```

### PDF landet nicht in Google Drive
```bash
gcloud functions logs read gcs-to-drive-sync --region=us-central1 --limit=20
```

### Notifications kommen gar nicht
1. Health Check grün?
2. Neue Einträge in Notion vorhanden?
3. Eintrag schon im State?
```bash
gsutil cat gs://reisekosten-workflow-state/reported_requests.json | grep PAGE_ID
```
4. Poll manuell triggern + Logs checken

### State zurücksetzen (Notfall)
```bash
# Achtung: alle Einträge werden beim nächsten Poll erneut gemeldet!
gsutil rm gs://reisekosten-workflow-state/reported_requests.json
```

## Secrets

```bash
gcloud secrets list
# Secret aktualisieren:
echo "xoxb-neuer-token" | gcloud secrets versions add SLACK_BOT_TOKEN --data-file=-
```

| Secret | Zweck |
|--------|-------|
| NOTION_SERVICE_ACCOUNT_JSON | Notion API |
| SLACK_BOT_TOKEN | Slack API |
| GCS_BUCKET_NAME | Bucket Name |
| REISEKOSTEN_FREIGABE_DB_ID | Antrags-DB |
| REISEKOSTEN_RECHNUNG_DB_ID | Rechnungs-DB |
| SLACK_CHANNEL_ID | Zielkanal |

## Wartungs-Checkliste

Täglich: Health Check
Wöchentlich: Cloud Run + Cloud Function Logs auf Errors prüfen
Monatlich: GCS Bucket auf verbliebene PDFs prüfen, Cloud-Kosten prüfen

## Was man NICHT tun sollte

- State-Datei manuell bearbeiten (außer Notfall)
- Notion DB-Struktur ändern (bricht Polling)
- Direkt auf main committen ohne lokalen Test
- Secrets in Code einchecken

## Kontakt

Thomas Blank
Email: thomas.blank.bw@gmx.de
Mobile: +49 171 3399891

**Version:** 4.0 — 19. Mai 2026
**Änderungen:** Formular, GCS Cleanup, Duplicate Fix, 403 Fix
