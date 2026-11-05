#!/usr/bin/env python3
"""Post an alert to Slack through a webhook. Stdlib only.

Works with a Slack "Incoming Webhook" URL and with a Workflow Builder webhook
whose variable is named `text` — both accept {"text": "..."}.

Best-effort: if SLACK_WEBHOOK_URL isn't configured, or Slack rejects the
post, it prints a note and exits 0 — the GitHub issue stays the source of
truth, so a Slack problem never fails or hides the real alert. The webhook
URL is a secret and is never printed.

Env:
    SLACK_WEBHOOK_URL  webhook URL (GitHub secret)
    SLACK_MENTION      optional, prepended to the message, e.g. "<@U012ABCDEF>"
    ALERT_TEXT         message text (Slack mrkdwn: *bold*, <url|label>)

Usage:
    python3 scripts/send_slack_alert.py            # text from ALERT_TEXT
    python3 scripts/send_slack_alert.py <file>     # text from a file
"""
import json
import os
import sys
import urllib.request


def main():
    url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            text = f.read().strip()
    else:
        text = os.environ.get("ALERT_TEXT", "").strip()
    if not text:
        print("no alert text — nothing to send")
        return
    if not url:
        print("SLACK_WEBHOOK_URL not set — skipping Slack (GitHub issue still alerts)")
        return
    mention = os.environ.get("SLACK_MENTION", "").strip()
    if mention:
        text = "%s %s" % (mention, text)

    req = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(200).decode("utf-8", "replace")
        print("Slack alert sent (%s)" % (body or "ok"))
    except Exception as e:  # noqa: BLE001 — Slack is best-effort; never echo the URL
        detail = getattr(e, "code", None) or type(e).__name__
        sys.stderr.write("Slack post failed (%s); the GitHub issue alert still fired\n" % detail)


if __name__ == "__main__":
    main()
