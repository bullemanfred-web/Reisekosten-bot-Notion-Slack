# 📋 Handover Documentation – What You Need to Know

**Project:** Reisekosten-Automation (Notion + Slack + Google Cloud)  
**Status:** ✅ Production-ready (v3 Final)  
**Last Updated:** 13. Mai 2026  
**Quality Score:** 8.5/10

---

## ⚡ Quick Start (5 minutes)

You're taking over the Reisekosten-Bot. Here's what you need to know right now:

### What does this system do?

A serverless bot that:
- Checks Notion databases every 60 minutes (via Cloud Scheduler)
- Finds new/updated requests and invoices
- Sends Slack notifications to the team
- Downloads invoice PDFs and stores them in Google Cloud Storage
- Prevents duplicate notifications using state tracking

### Where is it running?

- **Cloud Run:** `reisekosten-bot` in `europe-west1` (Frankfurt)
- **URL:** https://reisekosten-bot-20041081481.europe-west1.run.app
- **Health Check:** `curl https://reisekosten-bot-20041081481.europe-west1.run.app/health`

### Is it working?

Check right now:
```bash
curl https://reisekosten-bot-20041081481.europe-west1.run.app/health
```

If you get JSON with `"status": "healthy"` → ✅ All good  
If you get an error → See **Troubleshooting** section below

### Where's the documentation?

- **For system design:** Read `docs/ARCHITECTURE.md` (10 min read)
- **For troubleshooting:** Read `docs/OPERATIONAL_RUNBOOK.md` in Notion
- **For code quality:** Read `docs/CODE_REVIEW.md`
- **For future work:** Read `docs/IMPROVEMENTS.md`

---

## 🎯 Daily/Weekly Responsibilities

### What you need to do

#### Daily (5 minutes)
- [ ] Check health endpoint once per day
  ```bash
  curl https://reisekosten-bot-20041081481.europe-west1.run.app/health
  ```
- If status is not `healthy` → Check logs (see below)

#### Weekly (15 minutes)
- [ ] Review Cloud Run logs for any errors
  ```bash
  gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=reisekosten-bot" --limit 20
  ```
- Check if any ERROR or WARNING messages appear
- If yes → Escalate (see **Who to contact** below)

#### Monthly (30 minutes)
- [ ] Check PDF storage size (shouldn't grow too much)
  ```bash
  gsutil du -s gs://reisekosten-workflow-state/
  ```
- Check Cloud costs (should be €2-5/month)
- Check if any old PDFs can be archived/deleted

### What NOT to do

❌ **Don't touch the state file** (`reported_requests.json`) unless guided  
❌ **Don't redeploy without testing** (use GitHub Actions)  
❌ **Don't change Notion DB structure** (will break polling)  
❌ **Don't rotate secrets manually** (use Secret Manager)

---

## 🚀 Common Tasks

### Task 1: Test if the bot is working

```bash
# Check health
curl https://reisekosten-bot-20041081481.europe-west1.run.app/health

# Manually trigger a poll (don't wait 60 min)
gcloud scheduler jobs run check-reisekosten --location=europe-west1

# Check logs for any errors
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=reisekosten-bot" --limit 5
```

### Task 2: Deploy code changes

**Only if Thomas (or successor) made code changes:**

1. Pull the latest from GitHub
   ```bash
   cd /path/to/repo && git pull origin main
   ```

2. The GitHub Actions pipeline deploys automatically when you push to `main`

3. Verify deployment succeeded
   ```bash
   curl https://reisekosten-bot-20041081481.europe-west1.run.app/health
   ```

**Never deploy without testing locally first!**

### Task 3: Check archived invoices

```bash
# List all PDFs in storage
gsutil ls -r gs://reisekosten-workflow-state/rechnungen/

# Download a specific PDF for review
gsutil cp gs://reisekosten-workflow-state/rechnungen/FILENAME.pdf ~/Downloads/
```

### Task 4: Emergency: Reset state (if something breaks)

⚠️ **Only if instructed by Thomas or if state file is corrupted**

```bash
# View current state
gsutil cat gs://reisekosten-workflow-state/reported_requests.json | jq .

# Completely reset (next poll will re-send all notifications)
gsutil rm gs://reisekosten-workflow-state/reported_requests.json

# Or reset a single item (if stuck)
gsutil cp gs://reisekosten-workflow-state/reported_requests.json ./state.json
# Edit state.json to remove the bad entry
gsutil cp ./state.json gs://reisekosten-workflow-state/reported_requests.json
```

---

## 🛠️ Troubleshooting Guide

### Problem: Health check shows ERROR

**Step 1:** Check the logs
```bash
gcloud logging read "resource.type=cloud_run_revision AND severity=ERROR" --limit 10
```

**Step 2:** Look for these common errors:

| Error | Cause | Fix |
|-------|-------|-----|
| `401 Unauthorized` | Notion/Slack token invalid | Check Secret Manager |
| `404 Not Found` | Wrong database ID | Check `config.py` |
| `429 Too Many Requests` | Rate-limited | Wait 1 minute, retry |
| `503 Service Unavailable` | Notion/Slack is down | Check status page |

**Step 3:** If still stuck → Contact Thomas (see contacts below)

### Problem: Bot doesn't send notifications

**Checklist:**

1. ✅ Health endpoint is green?
   ```bash
   curl https://reisekosten-bot-20041081481.europe-west1.run.app/health
   ```

2. ✅ Are there new items in Notion with status != empty?
   - Go to Notion: Freigabe-DB or Rechnungs-DB
   - Check if new items exist

3. ✅ Was the item already processed before?
   ```bash
   gsutil cat gs://reisekosten-workflow-state/reported_requests.json | grep PAGE_ID
   ```
   - If the page ID is there → It was already sent
   - If not → It should have been sent

4. ✅ Is the Slack channel configured?
   - Check `#reisekosten-channel` exists
   - Check bot is in the channel

5. ✅ Manually trigger a poll
   ```bash
   gcloud scheduler jobs run check-reisekosten --location=europe-west1
   ```

### Problem: Cloud Run crashed

**Quick fix:**
```bash
# Redeploy from latest GitHub version
gcloud run deploy reisekosten-bot \
  --image eu.gcr.io/reisekosten-workflow/reisekosten-bot:latest \
  --region europe-west1 \
  --memory 1024Mi \
  --timeout 600s
```

Or wait for next GitHub Actions deployment (automatic on `main` push).

---

## 📞 Who to Contact & When

### Thomas Blank (Creator & Maintainer)

**Email:** thomas.blank.bw@gmx.de  
**Phone:** +49 171 3399891

**Contact when:**
- System is consistently broken (not recoverable)
- Need to make code changes or deploy
- Need to rotate credentials/secrets
- Want to implement improvements from IMPROVEMENTS.md

**Don't contact for:**
- Simple questions about how to use gcloud CLI
- General troubleshooting (check OPERATIONAL_RUNBOOK first)

### Blockchain Bundesverband IT Lead (if applicable)

**Contact when:**
- Cloud infrastructure issues (GCP project, permissions)
- Service account permissions need updating
- Billing questions

---

## 📚 Documentation Map

**What to read when:**

| Situation | Read This | Time |
|-----------|-----------|------|
| "How does the system work?" | ARCHITECTURE.md | 10 min |
| "It's broken, what do I do?" | OPERATIONAL_RUNBOOK.md (Notion) | 15 min |
| "I want to make code changes" | CODE_REVIEW.md | 15 min |
| "What else could we build?" | IMPROVEMENTS.md | 10 min |
| "How do I deploy changes?" | DEPLOYMENT guide (Notion) | 10 min |
| "I'm new, teach me everything" | Start with this file, then ARCHITECTURE.md | 30 min |

---

## 🔐 Secrets & Configuration

### All Secrets are in Google Secret Manager

Check what's there:
```bash
gcloud secrets list --filter 'name:reisekosten*'
```

**These secrets should exist:**

| Secret | Purpose | Managed By |
|--------|---------|------------|
| `NOTION_SERVICE_ACCOUNT_JSON` | Notion API access | Thomas |
| `SLACK_BOT_TOKEN` | Slack API access | Thomas / Slack Workspace Admin |
| `GCS_BUCKET_NAME` | Where PDFs are stored | Thomas |
| `REISEKOSTEN_FREIGABE_DB_ID` | Notion DB for requests | Thomas |
| `REISEKOSTEN_RECHNUNG_DB_ID` | Notion DB for invoices | Thomas |
| `SLACK_CHANNEL_ID` | Where notifications go | Thomas |

**If a secret is wrong/expired:**

1. Check Secret Manager:
   ```bash
   gcloud secrets describe SLACK_BOT_TOKEN
   ```

2. If token expired (e.g., Slack token):
   - Get new token from Slack workspace settings
   - Update Secret Manager:
     ```bash
     echo "xoxb-new-token-here" | gcloud secrets versions add SLACK_BOT_TOKEN --data-file=-
     ```
   - Redeploy Cloud Run (to pick up new secret):
     ```bash
     gcloud run deploy reisekosten-bot --region europe-west1 --image eu.gcr.io/reisekosten-workflow/reisekosten-bot:latest
     ```

---

## ⚙️ System Architecture (30-second summary)

```
Cloud Scheduler (every 60 min)
    ↓
Cloud Run Flask Server (/scheduled/check-all endpoint)
    ↓
Two parallel workflows:
  • polling.py → Query Freigabe-DB → Send Slack messages
  • polling_receipts.py → Query Rechnungs-DB → Send Slack + Download PDFs
    ↓
Cloud Storage (for state tracking & PDF archival)
    ↓
Slack (notifications sent to users)
```

**Key insight:** If Notion API fails → polling fails for that cycle but the bot retries next hour. If Slack fails → notifications don't send but polling completes. State is saved regardless.

---

## 🎓 Learning Path (if you want to understand the code)

**Hour 1:**
- [ ] Read ARCHITECTURE.md (10 min)
- [ ] Read this file end-to-end (10 min)
- [ ] Check health endpoint (2 min)
- [ ] Review Cloud Run logs (5 min)
- [ ] Look at `src/reisekosten_backend.py` (10 min) — It's the entry point
- [ ] Look at `src/polling.py` (15 min) — The main logic

**Hour 2:**
- [ ] Read CODE_REVIEW.md (15 min)
- [ ] Look at `src/config.py` (10 min) — Environment variables
- [ ] Look at `src/cloud_storage.py` (10 min) — State management
- [ ] Look at GitHub Actions workflow (5 min) — How deployment works
- [ ] Check Notion Technical Hub page (10 min)

**After 2 hours:** You should understand 80% of the system.

---

## 🚨 Emergency Procedures

### If the bot is down for more than 1 hour:

1. **Check health:**
   ```bash
   curl https://reisekosten-bot-20041081481.europe-west1.run.app/health
   ```

2. **Check logs:**
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND severity=ERROR" --limit 20
   ```

3. **Quick fix attempt:**
   ```bash
   gcloud run deploy reisekosten-bot \
     --region europe-west1 \
     --image eu.gcr.io/reisekosten-workflow/reisekosten-bot:latest
   ```

4. **If still down:** Contact Thomas with the error logs

### If state file is corrupted:

```bash
# Check state
gsutil cat gs://reisekosten-workflow-state/reported_requests.json | jq .

# If invalid JSON → Reset completely
gsutil rm gs://reisekosten-workflow-state/reported_requests.json

# Next poll will re-process everything (expect duplicate notifications for ~1 hour)
```

### If Slack notifications stopped but health is green:

1. Check Slack bot permissions:
   - Is bot in `#reisekosten-channel`?
   - Does bot have `chat:write` permission?

2. Check SLACK_BOT_TOKEN is valid:
   ```bash
   # Try a test message
   curl -X POST https://slack.com/api/auth.test \
     -H "Authorization: Bearer xoxb-YOUR-TOKEN"
   ```

3. If token invalid → Get new one from Slack, update Secret Manager (see Secrets section above)

---

## 📊 Monitoring Dashboard

**TODO for future:** Create Cloud Monitoring dashboard (see IMPROVEMENTS.md)

For now, manual checks:
- Health endpoint (daily)
- Cloud logs (weekly)
- PDF storage size (monthly)
- Cloud costs (monthly)

---

## 🎉 You're Ready!

You now have:
- ✅ System understanding
- ✅ Daily/weekly checklist
- ✅ Troubleshooting guide
- ✅ Emergency procedures
- ✅ Contact information
- ✅ Learning path

**If you get stuck:**
1. Check OPERATIONAL_RUNBOOK (Notion)
2. Review ARCHITECTURE.md
3. Check Cloud logs
4. Contact Thomas

---

## Checklist: First 24 Hours in Role

- [ ] Read this file completely
- [ ] Run health check: `curl https://...app/health`
- [ ] Review last 10 Cloud logs
- [ ] Add calendar reminder for weekly log review
- [ ] Bookmark the health check URL
- [ ] Save Thomas's contact info
- [ ] Read ARCHITECTURE.md
- [ ] Check Notion Technical Hub page
- [ ] Test manually triggering a poll:
  ```bash
  gcloud scheduler jobs run check-reisekosten --location=europe-west1
  ```
- [ ] Review docs/ folder structure

---

**Created:** 13. Mai 2026  
**Version:** 1.0 (v3 Final Handover)  
**Status:** Production-ready  
**Quality Score:** 8.5/10

**Questions?** Contact Thomas or check the relevant documentation section above.
