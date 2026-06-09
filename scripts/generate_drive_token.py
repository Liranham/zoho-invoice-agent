#!/usr/bin/env python3
"""
One-time Drive OAuth flow for Goldman.

Run this once. It opens a browser, asks you to allow Goldman to upload
files to your Google Drive, then writes GOLDMAN_DRIVE_TOKEN_B64 to .env
in the project root.

Reuses scripts/credentials.json (same OAuth client as Gmail). Scope:
drive.file — Goldman can only see/modify files HE creates. He cannot
read your personal Drive.

After this completes, restart Goldman (kill main.py and relaunch) so
the new env var is picked up.
"""

from __future__ import annotations

import base64
import pickle
import sys
from pathlib import Path

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Missing dependency. Run:")
    print("  python3 -m pip install --user google-auth google-auth-oauthlib google-auth-httplib2")
    sys.exit(1)


SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    here = Path(__file__).parent
    creds_path = here / "credentials.json"
    if not creds_path.exists():
        print(f"credentials.json missing at {creds_path}")
        sys.exit(1)

    print("Opening browser. Approve the Google permissions screen...")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    print("Authorization received.")

    pickled = pickle.dumps(creds)
    token_b64 = base64.b64encode(pickled).decode("ascii")

    env_path = here.parent / ".env"
    if not env_path.exists():
        print(f"Couldn't find {env_path}; printing token here instead:")
        print()
        print(f"GOLDMAN_DRIVE_TOKEN_B64={token_b64}")
        return

    text = env_path.read_text()
    new_line = f"GOLDMAN_DRIVE_TOKEN_B64={token_b64}"
    if "GOLDMAN_DRIVE_TOKEN_B64=" in text:
        new = []
        for line in text.splitlines():
            if line.startswith("GOLDMAN_DRIVE_TOKEN_B64="):
                new.append(new_line)
            else:
                new.append(line)
        env_path.write_text("\n".join(new) + "\n")
        print(f"Updated GOLDMAN_DRIVE_TOKEN_B64 in {env_path}")
    else:
        with env_path.open("a") as f:
            f.write(f"\n{new_line}\n")
        print(f"Appended GOLDMAN_DRIVE_TOKEN_B64 to {env_path}")

    print()
    print("Done. Restart Goldman so the new token loads:")
    print("  pkill -9 -f 'python3 main.py'")
    print("  cd ~/Desktop/Obsidian/Projects/zoho-invoice-agent && \\")
    print("    env -i HOME=\"$HOME\" PATH=\"$PATH\" PORT=10000 nohup python3 main.py > /tmp/goldman.log 2>&1 &")


if __name__ == "__main__":
    main()
