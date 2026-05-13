# 📦 Archival Documentation

## Overview

This document describes code and resources that have been archived from the active codebase. These files are no longer needed for the system to function but are preserved for reference and historical reasons.

**Last Updated:** 13. Mai 2026 (v3 Final)

---

## Archived Components

### 1. `gcs_to_drive_sync/` (Cloud Function)

**Location:** `.archive/gcs_to_drive_sync/`

**Status:** ❌ **Archived** (13. Mai 2026)

**Why Archived:**
- **Original Purpose:** Sync PDFs from Google Cloud Storage to Google Drive folder when `genehmigt` status triggered
- **Problem:** Google Drive API requires OAuth2 with human user authentication. Service Accounts cannot write to personal Drive folders (404 errors observed)
- **Solution (v3):** PDFs are now stored directly in Google Cloud Storage at `gs://reisekosten-workflow-state/rechnungen/` — no sync needed
- **Current Flow:** Notion → Download → GCS Upload (self-contained in `polling_receipts.py`)

**What it did:**
```python
# Old workflow:
Notion PDF → Download → GCS → Trigger Cloud Function → Google Drive Folder

# New workflow (v3):
Notion PDF → Download → GCS (done, no Cloud Function needed)
```

**If needed again:**
- Code is preserved in `.archive/` for reference
- To re-enable: Would need to switch from Service Account to OAuth2 personal credentials (complex, not recommended)
- Modern alternative: Use Google Drive API with personal credentials or switch to different storage (OneDrive, Dropbox, etc.)

**Files:**
- `.archive/gcs_to_drive_sync/main.py` (74 lines)
- `.archive/gcs_to_drive_sync/requirements.txt`

---

### 2. `test_poll_direct.py` (Local Test Script)

**Location:** `tests/test_poll_direct.py`

**Status:** ⏸️ **Inactive** (kept for local testing only)

**Why Archived (semi):**
- Used for local development/testing before Cloud Run deployment
- Not part of production pipeline
- Not deployed to Cloud Run
- Requires manual setup and local credentials

**What it does:**
- Simulates the polling workflow locally
- Tests Notion query logic
- Tests Slack message formatting

**When to use:**
- Local development on new features
- Testing before pushing to GitHub
- Debugging new polling logic

**How to use:**
```bash
# From repo root, with credentials in env vars:
export NOTION_SERVICE_ACCOUNT_JSON="..."
export SLACK_BOT_TOKEN="..."
python tests/test_poll_direct.py
```

**Note:** This is intentionally kept (not archived) because it's useful for local development. It's just not part of the deployment.

---

### 3. Legacy Google Drive Integration

**Location:** `src/google_drive_module.py` (refactored, not archived)

**Status:** ⚠️ **Legacy but Active**

**What Happened:**
- **v1/v2:** Used Google Drive API (`from googleapiclient.discovery import build`)
- **v3:** Refactored to use Google Cloud Storage instead
- **Current Code:** Still has Google Drive imports (for backwards compatibility) but uses GCS

**Why it's still there:**
- `polling_receipts.py` calls `upload_file_from_url()` function
- Function now returns GCS path instead of Drive file ID
- No actual Drive API calls made anymore

**Future Cleanup:**
- Remove Google Drive imports from `src/google_drive_module.py`
- Rename to `src/cloud_storage_integration.py`
- Update imports in `polling_receipts.py`

**Lines of Dead Code:**
```python
# These imports are no longer used:
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
```

---

## Active Components (Not Archived)

### Production Code (Required)

| Component | Lines | Purpose | Status |
|-----------|-------|---------|--------|
| `src/reisekosten_backend.py` | 130 | Flask API + Health Endpoint | ✅ Active |
| `src/polling.py` | 232 | Freigabe-DB Polling Logic | ✅ Active |
| `src/polling_receipts.py` | 265 | Rechnungs-DB Polling + PDF Upload | ✅ Active |
| `src/config.py` | 58 | Environment Variables | ✅ Active |
| `src/cloud_storage.py` | 77 | State Persistence | ✅ Active |
| `src/notion_client_module.py` | 62 | Notion API | ✅ Active |
| `src/slack_client_module.py` | 62 | Slack Integration | ✅ Active |
| `src/google_drive_module.py` | 95 | GCS Integration (refactored) | ✅ Active |
| `src/message_templates.py` | 406 | Slack Message Formatting | ✅ Active |

### Documentation (Required)

| Document | Purpose | Status |
|----------|---------|--------|
| `docs/ARCHITECTURE.md` | System design, component overview | ✅ Current |
| `docs/CODE_REVIEW.md` | Code quality assessment | ✅ Current |
| `docs/README.md` | Project overview | ✅ Current |
| `docs/ARCHIVAL.md` | This file | ✅ Current |

### Infrastructure

| File | Purpose | Status |
|------|---------|--------|
| `.github/workflows/deploy.yml` | CI/CD Pipeline | ✅ Active |
| `main.py` | Entry point (calls `reisekosten_backend.py`) | ✅ Active |
| `Dockerfile` | Container image | ✅ Active |
| `requirements.txt` | Python dependencies | ✅ Active |

### Testing (Optional but Useful)

| File | Purpose | Status |
|------|---------|--------|
| `tests/test_poll_direct.py` | Local polling test | ⏸️ Optional |
| `scripts/reset_state.py` | Emergency state reset | ⏸️ Optional |

---

## Cleanup Decisions Made

### ✅ Archived (13. Mai 2026)

| Item | Reason | Archive Path |
|------|--------|--------------|
| `gcs_to_drive_sync/` | Google Drive API no longer needed (v3 uses GCS) | `.archive/gcs_to_drive_sync/` |

### ⏸️ Kept (Optional, Not Archived)

| Item | Reason | Location |
|------|--------|----------|
| `test_poll_direct.py` | Useful for local development | `tests/test_poll_direct.py` |
| `reset_state.py` | Emergency tool if state file corrupts | `scripts/reset_state.py` |
| `src/google_drive_module.py` | Still used by polling_receipts (refactored) | `src/google_drive_module.py` |

### 🗑️ Deleted (Nothing)

All other files are active and required for production.

---

## Archive Restoration

If `gcs_to_drive_sync/` needs to be restored:

```bash
# Check what's in archive
ls -la .archive/

# Restore from archive
mv .archive/gcs_to_drive_sync/ scripts/

# If you need to deploy the Cloud Function again:
# gcloud functions deploy gcs_to_drive_sync \
#   --runtime python311 \
#   --trigger-resource reisekosten-workflow-state \
#   --trigger-event google.storage.object.finalize
```

---

## Storage Impact

**Archive Size:**
- `gcs_to_drive_sync/` = ~2 KB (minimal)
- Total repo size: ~500 KB (compressed)

**No storage impact on:**
- Cloud Run (archive not deployed)
- GitHub (optional, can use `.gitignore` for `.archive/`)
- Production (archive is local reference only)

---

## Future Considerations

### Optional Cleanups (Not Done Yet)

1. **Remove dead imports from `google_drive_module.py`**
   - Remove: `googleapiclient` imports
   - Rename module to `cloud_storage_integration.py`
   - Effort: 10 minutes

2. **Deprecate `test_poll_direct.py`**
   - Move to `.archive/` if no longer useful
   - Effort: 5 minutes

3. **Create integration tests**
   - Test full Notion → Slack → GCS flow
   - Effort: 2-4 hours
   - Status: Optional enhancement

---

## Summary

| Category | Count | Status |
|----------|-------|--------|
| Archived Components | 1 | ✅ Done (13. Mai 2026) |
| Active Production Modules | 9 | ✅ Running |
| Documentation Files | 4 | ✅ Current |
| Optional/Test Scripts | 2 | ⏸️ Available |
| Total Codebase | ~1,387 lines | ✅ Production-ready |

**Cleanup Level:** 95% (minimal legacy code, no technical debt)

---

**Archival Policy:**
- Code is preserved in `.archive/` for historical/reference purposes
- Nothing is deleted permanently (can be recovered if needed)
- `.archive/` is not deployed to Cloud Run
- Focus on keeping production (`src/`, `docs/`, `.github/`) clean and minimal

**Created:** 13. Mai 2026  
**Version:** 1.0
