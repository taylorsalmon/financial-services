# Gmail Setup

One-time setup to allow the digest agent to create drafts in your Gmail.

## Steps

### 1. Create Google Cloud credentials
1. Go to https://console.cloud.google.com
2. Create a new project (or use existing) — name it "QSR Digest"
3. Go to **APIs & Services → Library**
4. Search "Gmail API" → Enable it
5. Go to **APIs & Services → Credentials**
6. Click **Create Credentials → OAuth client ID**
7. Application type: **Desktop app**
8. Name: "QSR Digest"
9. Click Create → **Download JSON**
10. Rename the downloaded file to `gmail-credentials.json`
11. Move it to this folder: `managed-agent-cookbooks/qsr-digest/gmail-credentials.json`

### 2. Configure OAuth consent screen
1. Go to **APIs & Services → OAuth consent screen**
2. User type: **External**
3. Fill in app name: "QSR Digest", your email
4. Under **Scopes** → Add `https://www.googleapis.com/auth/gmail.compose`
5. Under **Test users** → Add your Gmail address

### 3. Add your email to .env
In `/Users/taylorsalmon/financial-services/.env` add:
```
DIGEST_TO_EMAIL=your@gmail.com
```

### 4. Run the auth flow (once only)
```bash
cd /Users/taylorsalmon/financial-services
source .env && python3 managed-agent-cookbooks/qsr-digest/demo.py
```
A browser window will open → sign in → grant permission.
A `gmail-token.json` file is saved. All future runs (including cron) use this token silently.

### 5. Done
The token auto-refreshes. You never need to do this again unless you revoke access.
