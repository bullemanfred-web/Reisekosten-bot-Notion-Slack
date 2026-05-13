# Reisekosten-Bot: Technische Architektur (v3)

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   CLOUD SCHEDULER                           │
│                   (Every 60 Minutes)                         │
│                   0 * * * * (UTC)                            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              GOOGLE CLOUD RUN                               │
│         reisekosten-bot (europe-west1)                      │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           Flask Web Server (gunicorn)                │  │
│  │    reisekosten_backend.py (reisekosten_backend.py)   │  │
│  │                                                      │  │
│  │  GET  /health                 → Health Check        │  │
│  │  POST /scheduled/check-all     → Trigger Polling    │  │
│  └──────────────────────────────────────────────────────┘  │
│                     │                                       │
│       ┌─────────────┴─────────────┐                         │
│       ▼                           ▼                         │
│  ┌──────────────────┐     ┌──────────────────┐             │
│  │ POLLING WORKFLOW │     │ POLLING WORKFLOW │             │
│  │  (Anträge)       │     │  (Rechnungen)    │             │
│  │ polling.py       │     │ polling_receipts │             │
│  └──────────────────┘     └──────────────────┘             │
│       │                           │                         │
└───────┼───────────────────────────┼─────────────────────────┘
        │                           │
        ▼                           ▼
   ┌────────────────┐      ┌──────────────────┐
   │   NOTION API   │      │   NOTION API     │
   │ Freigabe-DB    │      │ Rechnungs-DB     │
   │                │      │                  │
   │ Status Query   │      │ Status Query     │
   │ (60 min cycle) │      │ (60 min cycle)   │
   └────────────────┘      └──────────────────┘
        │                           │
        ├─────────────┬─────────────┤
        │             │             │
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────────┐
   │  Slack  │  │   Cloud  │  │  Google      │
   │   API   │  │ Storage  │  │ Cloud        │
   │         │  │          │  │ Storage      │
   │ DMs +   │  │ State:   │  │              │
   │ Channel │  │ reported │  │ PDF Archive: │
   │Messages │  │_requests │  │ rechnungen/  │
   └─────────┘  └──────────┘  └──────────────┘
```

---

## Component Architecture

### 1. **Frontend Layer** (Cloud Scheduler)

**Trigger:** Cloud Scheduler Job `check-reisekosten`
- **Schedule:** `0 * * * *` (every hour at :00)
- **Method:** HTTP POST to `/scheduled/check-all`
- **Payload:** JSON with optional `force_reprocess` parameter (debug)

### 2. **API Layer** (reisekosten_backend.py)

**Flask Web Server** running on Cloud Run

**Endpoints:**
- `GET /health` – Health check, returns service status
- `POST /scheduled/check-all` – Triggered by Cloud Scheduler, starts polling in background thread

**Threading Model:**
- Each request spawns a daemon thread to avoid blocking scheduler response
- Returns immediately with 200 OK (async processing)

### 3. **Polling Layer** (polling.py + polling_receipts.py)

Two parallel polling workflows:

#### Workflow 1: Freigabe-Polling (polling.py)
1. Load `reported_requests` from Cloud Storage
2. Query Notion Freigabe-DB for items with Status != empty
3. For each item:
   - Extract properties (Status, Email, Amount, etc.)
   - Check if status changed: `status != reported_requests[page_id]`
   - If changed: send Slack notification (Channel or DM)
   - Update `reported_requests[page_id] = status`
4. Save `reported_requests` back to Cloud Storage

#### Workflow 2: Rechnungs-Polling (polling_receipts.py)
1. Load `reported_requests` from Cloud Storage
2. Query Notion Rechnungs-DB for items with Status != empty
3. For each item:
   - Extract properties (Status, Title, Amount, Email, PDFs, etc.)
   - Check if status changed
   - If changed:
     - Send Slack DM notification
     - **If Status = "Genehmigt":** Download PDFs from Notion → Upload to GCS
   - Update `reported_requests[page_id] = status`
4. Save `reported_requests` back to Cloud Storage

**State Deduplication:**
- Only process items where `status != last_recorded_status`
- This prevents duplicate notifications on subsequent polls
- State is stored as `Dict[page_id] → status` in Cloud Storage

### 4. **Integration Modules**

#### notion_client_module.py
- Initializes Notion SDK Client
- Extracts `access_token` from `NOTION_SERVICE_ACCOUNT_JSON`
- Provides `get_notion_client()` function

#### slack_client_module.py
- Initializes Slack WebClient
- Provides `send_slack_dm()` helper to send DMs by email
- Uses `users.lookupByEmail` → `chat_postMessage`

#### google_drive_module.py (v3: GCS Integration)
- Initializes Google Cloud Storage Client
- Provides `upload_file_from_url()` function:
  1. Download PDF from Notion URL
  2. Create temporary file
  3. Upload to GCS bucket
  4. Return GCS path (gs://bucket/rechnungen/filename)
  5. Delete temp file

#### cloud_storage.py (State Management)
- `load_reported_requests()` – Read JSON from GCS blob
- `save_reported_requests()` – Write JSON to GCS blob
- Converts state between Dict format and JSON

#### message_templates.py
- Build Slack Block Kit messages for different scenarios:
  - New request (channel)
  - Approval DM
  - Rejection DM
  - New receipt (channel)
  - Receipt approval DM
  - Receipt rejection DM

#### config.py
- Load environment variables
- Decode base64 credentials (for Cloud Run)
- Parse JSON credentials
- Provide constants (DB IDs, bucket names, etc.)

---

## Data Flow

### State Persistence

```
Cloud Storage (GCS):
┌─────────────────────────────────────────┐
│ gs://reisekosten-workflow-state/        │
│                                         │
│ ├── reported_requests.json              │
│ │   {                                   │
│ │     "reported_requests": {            │
│ │       "page-id-1": "Genehmigt",       │
│ │       "page-id-2": "Abgelehnt",       │
│ │       "page-id-3": "Eingereicht"      │
│ │     },                                │
│ │     "last_updated": "2026-05-11T..."  │
│ │   }                                   │
│ │                                       │
│ └── rechnungen/                         │
│     ├── file1.pdf                       │
│     ├── file2.pdf                       │
│     └── file3.pdf                       │
└─────────────────────────────────────────┘
```

### Polling Cycle

```
Minute 0:
├─ Cloud Scheduler triggers /scheduled/check-all
├─ reisekosten_backend spawns background thread
├─ polling.py: Load state → Query Freigabe-DB → Process items → Save state
├─ polling_receipts.py: Load state → Query Rechnungs-DB → Process items + PDFs → Save state
├─ Both complete within 60 seconds
└─ HTTP 200 response sent

Minute 60:
└─ Repeat
```

---

## Deployment Model

### Cloud Run Configuration

| Setting | Value |
|---------|-------|
| Service | reisekosten-bot |
| Region | europe-west1 (Frankfurt) |
| Memory | 1 GB |
| CPU | 2 |
| Timeout | 600s |
| Instances | 1 (always on) |
| Execution Role | reisekosten-bot@reisekosten-workflow.iam.gserviceaccount.com |

### Service Account Permissions

**reisekosten-bot** Service Account has:
- ✅ Notion API token (via environment variable)
- ✅ Slack Bot token (via environment variable)
- ✅ GCS bucket read/write permissions (`roles/storage.objectAdmin` on bucket)
- ✅ Cloud Logging write (automatic)

### GitHub Actions CI/CD

**Trigger:** Push to `main` branch

**Workflow:**
1. `actions/checkout@v4` – Clone repo
2. `google-github-actions/auth@v2` – Auth with GCP
3. `google-github-actions/setup-gcloud@v2` – Setup gcloud CLI
4. `docker build` – Build Docker image
5. `docker push` – Push to Google Container Registry (eu.gcr.io)
6. `gcloud run deploy` – Deploy to Cloud Run
7. `curl /health` – Health check

**Image:** `eu.gcr.io/reisekosten-workflow/reisekosten-bot:latest`

---

## Error Handling & Resilience

### Error Recovery

| Scenario | Handling |
|----------|----------|
| Notion API unavailable | Log error, skip poll, return error in response |
| Slack API unavailable | Log error, continue polling, don't retry |
| PDF download fails | Log warning, skip that PDF, continue |
| Cloud Storage unreachable | Log error, use empty state (RAM-only) |
| Invalid JSON in state | Log warning, reset to empty dict |

### Logging Levels

- `DEBUG`: Detailed per-item processing (every page)
- `INFO`: Poll start/end, successful operations, counts
- `WARNING`: Recoverable errors (missing properties, API errors)
- `ERROR`: Critical failures (no Notion client, parse errors)

---

## Security Model

### Secrets Management

**Cloud Run Secret Manager:**
- `NOTION_SERVICE_ACCOUNT_JSON` – Service account JSON
- `SLACK_BOT_TOKEN` – Slack bot token
- `GOOGLE_DRIVE_CREDENTIALS_B64` – Base64 encoded credentials (legacy, not used in v3)

**Injection Method:**
- Environment variables in Cloud Run

**No secrets in:**
- GitHub repo (checked via .gitignore)
- Docker image
- Cloud Storage
- Logs (tokens are masked)

### API Permissions

**Notion Service Account:**
- Read Freigabe-DB
- Read Rechnungs-DB
- Read properties, relations, files

**Slack Bot:**
- `users:read` – Look up users by email
- `users:read.email` – Access email addresses
- `chat:write` – Send messages

**GCS Service Account:**
- Read/write on `reisekosten-workflow-state` bucket

---

## Monitoring & Observability

### Health Check Endpoint

```
GET /health

Response (200 OK):
{
  "status": "healthy",
  "timestamp": "2026-05-11T18:00:00Z",
  "clients": {
    "slack_configured": true,
    "notion_configured": true,
    "google_drive_configured": true
  },
  "polling": {
    "last_check": "2026-05-11T17:00:00Z",
    "mode": "API Polling (60 min)"
  },
  "last_error": null
}
```

### Cloud Logging

**Log Streams:**
- `resource.type=cloud_run_revision`
- `resource.labels.service_name=reisekosten-bot`

**Query Examples:**
```bash
# Last 50 logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=reisekosten-bot" --limit 50

# Errors only
gcloud logging read "resource.type=cloud_run_revision AND severity=ERROR" --limit 20

# PDF uploads
gcloud logging read "textPayload=~'GCS|PDF|Upload'" --limit 10
```

---

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Notion Query Time | ~200-500ms |
| Per-item Processing | ~10-20ms |
| PDF Download | ~1-5s (depends on file size) |
| GCS Upload | ~2-10s (depends on file size) |
| Cloud Storage Read | ~100-200ms |
| Cloud Storage Write | ~100-200ms |
| **Total Poll Time** | **~5-30s** (varies with PDF count) |

---

## Future Enhancements

1. **Metrics Integration** – Cloud Monitoring metrics (poll duration, errors, etc.)
2. **Dead Letter Queue** – Failed items stored for manual review
3. **Circuit Breaker** – Graceful degradation if APIs are flaky
4. **Caching Layer** – Cache Notion query results for 5 min
5. **Retries** – Exponential backoff for transient failures
6. **Multi-region** – Deploy to multiple Cloud Run regions

---

**Last Updated:** 11. Mai 2026 (v3 Final)
**Architecture Version:** 3.0 (Poll-based, Modular, GCS State, PDF Upload)
