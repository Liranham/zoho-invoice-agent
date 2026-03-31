# Gmail Automation Setup Guide

This guide explains how to set up automatic invoice creation from Wise transfer emails.

## 🎯 How It Works

1. **Email Arrives**: Wise sends "You received $X from Y" email to your Gmail
2. **Label Filter**: Email is automatically labeled "Pacific wise transfers"
3. **Webhook Triggered**: Gmail notifies your agent via webhook
4. **Parse & Match**: Agent extracts amount + sender, matches to client template
5. **Create Invoice**: Auto-creates invoice in Zoho Books
6. **Telegram Notification**: Sends confirmation to your Telegram

## 📋 Prerequisites

- Gmail account with "Pacific wise transfers" label
- Google Cloud Project with Gmail API enabled
- OAuth2 credentials for Gmail
- Telegram bot (optional, for notifications)
- Render deployment (or any public webhook endpoint)

## 🔧 Step 1: Set Up Gmail API

### 1.1 Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create new project: "Zoho Invoice Agent"
3. Enable Gmail API:
   - Navigate to "APIs & Services" > "Library"
   - Search for "Gmail API"
   - Click "Enable"

### 1.2 Create OAuth2 Credentials

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "OAuth client ID"
3. Application type: "Desktop app"
4. Name: "Zoho Invoice Agent"
5. Download credentials → save as `credentials.json`

### 1.3 Generate Token

Run this script locally to authorize and generate `token.json`:

```python
# generate_gmail_token.py
import os
import pickle
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def main():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)

        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    # Save token as JSON
    import json
    token_data = {
        'token': creds.token,
        'refresh_token': creds.refresh_token,
        'token_uri': creds.token_uri,
        'client_id': creds.client_id,
        'client_secret': creds.client_secret,
        'scopes': creds.scopes
    }
    with open('token.json', 'w') as f:
        json.dump(token_data, f)

    print("Token saved to token.json")

if __name__ == '__main__':
    main()
```

Run: `python3 generate_gmail_token.py`

### 1.4 Encode Credentials

```bash
# Encode for environment variables
base64 -i credentials.json -o credentials.b64
base64 -i token.json -o token.b64

# Or in one line for .env:
echo "GMAIL_CREDENTIALS_B64=$(base64 -i credentials.json)"
echo "GMAIL_TOKEN_B64=$(base64 -i token.json)"
```

## 🔧 Step 2: Set Up Telegram Bot (Optional)

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow prompts
3. Copy bot token (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)
4. Get your chat ID:
   - Message your bot
   - Visit: `https://api.telegram.org/bot<TOKEN>/getUpdates`
   - Find `"chat":{"id":12345678}` in response

## 🔧 Step 3: Configure Environment Variables

Update your `.env` file:

```env
# Gmail Settings
GMAIL_ENABLED=true
GMAIL_CREDENTIALS_B64=<base64 from step 1.4>
GMAIL_TOKEN_B64=<base64 from step 1.4>
GMAIL_LABEL_NAME=Pacific wise transfers

# Telegram Settings (optional)
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=<from step 2>
TELEGRAM_CHAT_ID=<from step 2>
```

## 🔧 Step 4: Update Client Mapping

Edit `gmail/automation.py` and update the `CLIENT_MAPPING` dict with your actual Zoho customer IDs:

```python
CLIENT_MAPPING = {
    "GILAD WEINBERG": "5889131000000080107",  # Your actual customer ID
    "AMZEXPERTGLOBALL": "5889131000000080001",  # Your actual customer ID
}
```

To find customer IDs:
```bash
python3 main.py --cli customers
```

## 🔧 Step 5: Deploy to Render

### 5.1 Push to GitHub

```bash
cd zoho-invoice-agent
git add .
git commit -m "Add Gmail automation"
git push
```

### 5.2 Set Environment Variables on Render

Using Render dashboard or API, add all env vars from Step 3.

### 5.3 Deploy

```bash
# Trigger deploy via API or dashboard
curl -X POST "https://api.render.com/v1/services/<service-id>/deploys" \
  -H "Authorization: Bearer <render-api-key>"
```

## 🔧 Step 6: Test the Integration

### 6.1 Test Email Parsing (Local)

Create a test script:

```python
# test_gmail.py
from gmail.parser import WiseEmailParser

email_body = """
Hello Liran,

You received 2,793.89 USD from GILAD WEINBERG &.

And it's already waiting in your account, ready to use.
"""

transfer = WiseEmailParser.parse(email_body)
print(f"Amount: ${transfer.amount}")
print(f"Sender: {transfer.sender_name}")
print(f"Date: {transfer.date}")
```

### 6.2 Test Manual Trigger

```bash
# POST to your webhook with a test message
curl -X POST "https://zoho-invoice-agent.onrender.com/webhook/gmail" \
  -H "Content-Type: application/json" \
  -d '{"test": true}'
```

Check logs for processing.

## 🔧 Step 7: Set Up Gmail Watch (Optional - For Real-time Push)

For real-time push notifications (instead of polling), you need Google Cloud Pub/Sub:

1. Enable Cloud Pub/Sub API in GCP
2. Create topic: `gmail-notifications`
3. Create push subscription pointing to your webhook
4. Set up watch:

```python
# setup_watch.py
from gmail.auth import GmailAuth
from gmail.watcher import GmailWatcher
import os

auth = GmailAuth(
    credentials_b64=os.getenv("GMAIL_CREDENTIALS_B64"),
    token_b64=os.getenv("GMAIL_TOKEN_B64")
)
watcher = GmailWatcher(auth, "Pacific wise transfers")
watcher.initialize()
watcher.setup_push_notifications(
    webhook_url="https://zoho-invoice-agent.onrender.com/webhook/gmail",
    topic_name="projects/YOUR-PROJECT-ID/topics/gmail-notifications"
)
```

**Note:** For free tier, polling mode (checking recent emails) is simpler and works fine for occasional wires.

## 🧪 Testing Workflow

1. **Send test wire**: Ask Gilad to send a small test wire
2. **Check Gmail**: Verify email arrives in "Pacific wise transfers" label
3. **Check logs**: Watch Render logs for parsing + invoice creation
4. **Check Telegram**: Should receive notification
5. **Check Zoho**: Verify invoice created correctly

## 🐛 Troubleshooting

### Email not parsed
- Check email format matches pattern in `gmail/parser.py`
- Look for: "You received X.XX USD from SENDER."

### Client not matched
- Check sender name in email vs. `CLIENT_MAPPING` in `gmail/automation.py`
- Names are case-insensitive and support partial matching

### Invoice creation fails
- Verify customer ID exists in Zoho
- Check template matches client in `invoice_templates.py`

### No Telegram notification
- Verify bot token and chat ID
- Check Render logs for Telegram API errors

## 📊 Flow Diagram

```
┌─────────────────┐
│  Wise Transfer  │
└────────┬────────┘
         │
         v
┌─────────────────┐
│  Gmail Inbox    │
└────────┬────────┘
         │
         v
┌─────────────────────────┐
│  "Pacific wise          │
│   transfers" Label      │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  Gmail Webhook →        │
│  /webhook/gmail         │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  Parse Email            │
│  Amount + Sender        │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  Match to Client        │
│  Template (HK/IL)       │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  Create Invoice in      │
│  Zoho Books             │
└────────┬────────────────┘
         │
         v
┌─────────────────────────┐
│  Send Telegram          │
│  Notification ✅        │
└─────────────────────────┘
```

## 🚀 Next Steps

1. ✅ Set up Gmail OAuth (Step 1)
2. ✅ Set up Telegram bot (Step 2)
3. ✅ Update client mapping (Step 4)
4. ✅ Deploy to Render (Step 5)
5. ✅ Test with real wire (Step 7)

Questions? Check logs first: `render logs -t zoho-invoice-agent`
