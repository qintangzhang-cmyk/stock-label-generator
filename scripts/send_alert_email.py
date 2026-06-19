#!/usr/bin/env python3
"""
Send a failure-alert email via Gmail SMTP. Self-contained (stdlib smtplib only,
no third-party action). Called by the Fetch Quotes and Watchdog workflows when
they detect a problem.

If MAIL_USERNAME / MAIL_PASSWORD aren't configured, it prints a warning and
exits 0 — the GitHub issue alert still fires, so a missing email secret never
fails the workflow.

Env:
    MAIL_USERNAME   sending Gmail address (also the SMTP login)
    MAIL_PASSWORD   Gmail App Password (16 chars, NOT the account password)
    ALERT_EMAILS    comma-separated recipient list
    ALERT_SUBJECT   subject line
    ALERT_BODY      plain-text body
"""
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage


def main():
    user = os.environ.get("MAIL_USERNAME", "").strip()
    pw = os.environ.get("MAIL_PASSWORD", "").strip()
    recipients = [a.strip() for a in os.environ.get("ALERT_EMAILS", "").replace(";", ",").split(",") if a.strip()]

    if not user or not pw:
        print("MAIL_USERNAME/MAIL_PASSWORD not set — skipping email (GitHub issue still alerts)")
        return
    if not recipients:
        print("ALERT_EMAILS empty — nothing to send")
        return

    msg = EmailMessage()
    msg["From"] = "Stock Label Bot <%s>" % user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = os.environ.get("ALERT_SUBJECT", "Stock Label alert")
    msg.set_content(os.environ.get("ALERT_BODY", ""))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as s:
            s.login(user, pw)
            s.send_message(msg)
        print("alert email sent to: %s" % ", ".join(recipients))
    except Exception as e:  # noqa: BLE001 — email is best-effort; issue is the source of truth
        sys.stderr.write("email send failed (issue alert still fired): %s\n" % e)


if __name__ == "__main__":
    main()
