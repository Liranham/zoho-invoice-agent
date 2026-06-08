"""Goldman Postgres access layer.

Two roles:
- admin connection: schema migrations and one-off ops (super-admin / service-role).
- app connection: restricted role goldman_app — what runtime code uses.

Always prefer the app connection. Reach for admin only inside migrate.py
or explicit admin scripts.
"""
