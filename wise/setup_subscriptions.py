"""
Subscribe (or list) Wise webhooks for the configured profile.

Usage:
    python3 -m wise.setup_subscriptions list-profiles
    python3 -m wise.setup_subscriptions list
    python3 -m wise.setup_subscriptions subscribe   # idempotent
    python3 -m wise.setup_subscriptions delete <subscription_id>

Reads WISE_API_TOKEN, WISE_PROFILE_ID, WISE_WEBHOOK_BASE_URL from env.
The delivery URL is `<base>/webhook/wise`.
"""

from __future__ import annotations

import logging
import os
import sys

import click

from config.settings import Settings
from wise.auth import WiseAuth
from wise.client import WiseClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger(__name__)

EVENTS = ["transfers#state-change", "balances#credit"]
# Note: swift-in#credit is a separate product and may need to be enabled in
# Wise UI before subscription. We try it but warn on failure.
SWIFT_EVENT = "swift-in#credit"


def _build_client() -> tuple[WiseClient, str]:
    settings = Settings()
    token = os.environ.get("WISE_API_TOKEN") or settings.__dict__.get("wise_api_token", "")
    profile_id = os.environ.get("WISE_PROFILE_ID", "")
    if not token:
        raise SystemExit("WISE_API_TOKEN not set")
    auth = WiseAuth(token)
    return WiseClient(auth), profile_id


@click.group()
def cli():
    pass


@cli.command("list-profiles")
def list_profiles_cmd():
    client, _ = _build_client()
    profiles = client.list_profiles()
    for p in profiles:
        click.echo(f"{p.get('id')}  {p.get('type')}  {p.get('details', {}).get('name', '')}")


@cli.command("list")
def list_cmd():
    client, profile_id = _build_client()
    if not profile_id:
        raise SystemExit("WISE_PROFILE_ID not set")
    subs = client.list_subscriptions(profile_id)
    if not subs:
        click.echo("(no subscriptions)")
        return
    for s in subs:
        click.echo(
            f"{s.get('id')}  {s.get('trigger_on')}  -> {s.get('delivery', {}).get('url')}  "
            f"({s.get('name')})"
        )


@cli.command("subscribe")
def subscribe_cmd():
    """Idempotent: only creates subscriptions that don't already exist."""
    client, profile_id = _build_client()
    base_url = os.environ.get("WISE_WEBHOOK_BASE_URL", "").rstrip("/")
    if not profile_id or not base_url:
        raise SystemExit("WISE_PROFILE_ID and WISE_WEBHOOK_BASE_URL required")

    delivery_url = f"{base_url}/webhook/wise"
    existing = client.list_subscriptions(profile_id)
    existing_keys = {(s.get("trigger_on"), s.get("delivery", {}).get("url")) for s in existing}

    for event in EVENTS:
        if (event, delivery_url) in existing_keys:
            click.echo(f"✓ {event}: already subscribed")
            continue
        sub = client.subscribe_webhook(profile_id, event, delivery_url)
        click.echo(f"+ {event}: created (id={sub.get('id')})")

    # SWIFT — best-effort
    if (SWIFT_EVENT, delivery_url) in existing_keys:
        click.echo(f"✓ {SWIFT_EVENT}: already subscribed")
    else:
        try:
            sub = client.subscribe_webhook(profile_id, SWIFT_EVENT, delivery_url)
            click.echo(f"+ {SWIFT_EVENT}: created (id={sub.get('id')})")
        except Exception as e:
            click.echo(
                f"⚠ {SWIFT_EVENT}: could not subscribe ({e}). "
                "May need to enable SWIFT-in receipts in Wise UI first."
            )


@cli.command("delete")
@click.argument("subscription_id")
def delete_cmd(subscription_id: str):
    client, profile_id = _build_client()
    if not profile_id:
        raise SystemExit("WISE_PROFILE_ID not set")
    client.delete_subscription(profile_id, subscription_id)
    click.echo(f"deleted: {subscription_id}")


if __name__ == "__main__":
    cli()
