#!/usr/bin/env python3
"""
Report how much life the Longbridge access token has left.

Used by the failure path in fetch-quotes.yml to tell two very different
situations apart:

  * days left <= 0   → the token genuinely expired; renewal never ran or failed
  * days left > 0    → the token was revoked server-side (regenerated in 用戶中心,
                       password change, account/permission change). Renewal was
                       working fine and is NOT the culprit.

Getting this wrong costs real time: on 2026-09-07 the alert asserted "token
expired", but the token still had 70.9 days on it — it had been revoked.

Prints a single line to stdout, e.g. "70.9" or "-3.2", or "unknown" when the
token can't be decoded. Never prints the token itself.

Usage:
    python3 scripts/token_days_left.py
Env: LONGBRIDGE_ACCESS_TOKEN
"""
import base64
import json
import os
import sys
from datetime import datetime, timezone


def days_left(token):
    # token looks like "m_<header>.<payload>.<sig>"; read the JWT payload's exp
    jwt = token.split("_", 1)[-1]
    payload = jwt.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    exp = datetime.fromtimestamp(claims["exp"], timezone.utc)
    return (exp - datetime.now(timezone.utc)).total_seconds() / 86400


def main():
    token = os.environ.get("LONGBRIDGE_ACCESS_TOKEN", "")
    if not token:
        print("unknown")
        return
    try:
        print("%.1f" % days_left(token))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("could not decode token exp: %s\n" % e)
        print("unknown")


if __name__ == "__main__":
    main()
