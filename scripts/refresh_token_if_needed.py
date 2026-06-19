#!/usr/bin/env python3
"""
Refresh the Longbridge API-Key access token when it's close to expiring.

The access token (a JWT) is valid 90 days. This decodes its `exp`, and if fewer
than THRESHOLD_DAYS remain, calls Config.refresh_access_token() to mint a fresh
90-day token. The new token is written to the file path given as argv[1] — it is
NEVER printed to stdout (would leak into CI logs). stdout carries only a status
word the workflow can branch on:

    REFRESHED   — a new token was written to the output file; store it
    NO_REFRESH  — plenty of life left; do nothing
    ERROR       — something failed; workflow keeps the existing token

Usage:
    python3 scripts/refresh_token_if_needed.py /tmp/new_token
Env: LONGBRIDGE_APP_KEY / LONGBRIDGE_APP_SECRET / LONGBRIDGE_ACCESS_TOKEN
     REFRESH_THRESHOLD_DAYS (optional, default 30)
"""
import base64
import json
import os
import sys
from datetime import datetime, timezone, timedelta


def token_days_left(token):
    # token looks like "m_<header>.<payload>.<sig>"; decode the JWT payload's exp
    jwt = token.split("_", 1)[-1]
    payload = jwt.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload))
    exp = datetime.fromtimestamp(claims["exp"], timezone.utc)
    return (exp - datetime.now(timezone.utc)).total_seconds() / 86400


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/new_token"
    threshold = float(os.environ.get("REFRESH_THRESHOLD_DAYS", "30"))
    token = os.environ.get("LONGBRIDGE_ACCESS_TOKEN", "")

    try:
        days = token_days_left(token)
    except Exception as e:  # noqa: BLE001 — can't decode → don't risk a refresh
        sys.stderr.write("could not decode token exp: %s\n" % e)
        print("ERROR")
        return

    sys.stderr.write("access token has %.1f days left (threshold %.0f)\n" % (days, threshold))
    if days >= threshold:
        print("NO_REFRESH")
        return

    try:
        from longbridge.openapi import Config
        cfg = Config.from_apikey_env()
        new_token = cfg.refresh_access_token(
            datetime.now(timezone.utc) + timedelta(days=90)
        )
        if not new_token or "." not in new_token:
            sys.stderr.write("refresh returned an unexpected value\n")
            print("ERROR")
            return
        with open(out_path, "w") as f:
            f.write(new_token)
        sys.stderr.write("refreshed; new token has %.1f days left\n" % token_days_left(new_token))
        print("REFRESHED")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("refresh_access_token failed: %s\n" % e)
        print("ERROR")


if __name__ == "__main__":
    main()
