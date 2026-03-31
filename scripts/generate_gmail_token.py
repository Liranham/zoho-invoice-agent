#!/usr/bin/env python3
"""
Generate Gmail API token for the Zoho Invoice Agent.

Prerequisites:
1. Download credentials.json from Google Cloud Console
2. Place it in the same directory as this script

This script will:
1. Open browser for OAuth2 authorization
2. Generate token.json with refresh token
3. Display base64-encoded values for .env
"""

import json
import os
import sys
from pathlib import Path

try:
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
except ImportError:
    print("Error: google-auth packages not installed")
    print("Run: pip install google-auth google-auth-oauthlib google-auth-httplib2")
    sys.exit(1)

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def main():
    script_dir = Path(__file__).parent
    creds_file = script_dir / 'credentials.json'
    token_file = script_dir / 'token.json'

    # Check if credentials.json exists
    if not creds_file.exists():
        print("❌ credentials.json not found!")
        print("\nSteps to get credentials.json:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create/select project")
        print("3. Enable Gmail API")
        print("4. Create OAuth2 credentials (Desktop app)")
        print("5. Download credentials.json")
        print(f"6. Place it in: {script_dir}/")
        sys.exit(1)

    print("🔐 Starting Gmail OAuth2 flow...\n")

    creds = None

    # Load existing token if available
    if token_file.exists():
        print("Found existing token.json")
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    # Refresh or create new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("Opening browser for authorization...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(creds_file), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token
        token_data = {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret,
            'scopes': creds.scopes
        }
        with open(token_file, 'w') as f:
            json.dump(token_data, f, indent=2)
        print(f"✅ Token saved to: {token_file}\n")

    # Generate base64-encoded values for .env
    import base64

    with open(creds_file, 'rb') as f:
        creds_b64 = base64.b64encode(f.read()).decode('utf-8')

    with open(token_file, 'rb') as f:
        token_b64 = base64.b64encode(f.read()).decode('utf-8')

    print("=" * 70)
    print("📋 Environment Variables for .env")
    print("=" * 70)
    print("\nGMAIL_ENABLED=true")
    print(f"GMAIL_CREDENTIALS_B64={creds_b64}")
    print(f"GMAIL_TOKEN_B64={token_b64}")
    print("GMAIL_LABEL_NAME=Pacific wise transfers")
    print("\n" + "=" * 70)
    print("\n✅ Setup complete! Copy the above to your .env file or Render settings.")


if __name__ == '__main__':
    main()
