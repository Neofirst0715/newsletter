"""
send.py -- Layer 3 of the newsletter pipeline: sending.

Sends the final newsletter body over Gmail SMTP (SSL, port 465) using only
the standard library (smtplib + email.mime). Credentials and the recipient
come from .env via python-dotenv -- never hardcoded.

On a successful send, the events that went into this newsletter are marked
as sent in state/sent_log.json so collect.py's dedupe won't resurface them.
On any failure, nothing is marked as sent, so the same events are picked
up again next run.
"""

import json
import logging
import smtplib
import ssl
from datetime import date
from email.mime.text import MIMEText
from pathlib import Path

from collect import _event_key
from config import RECIPIENT_EMAIL, SENDER_APP_PASSWORD, SENDER_EMAIL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

STATE_FILE = Path(__file__).parent / "state" / "sent_log.json"


def _mark_as_sent(events: list) -> None:
    """Append these events' keys to state/sent_log.json without overwriting existing entries."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    if STATE_FILE.exists():
        try:
            loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except (json.JSONDecodeError, OSError):
            logger.exception("_mark_as_sent: could not read existing sent_log.json, starting fresh")

    existing_set = set(existing)
    for event in events:
        key = _event_key(event)
        if key not in existing_set:
            existing.append(key)
            existing_set.add(key)

    STATE_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def send_newsletter(body: str, events: list) -> bool:
    """
    Send `body` as the newsletter email over Gmail SMTP.

    `events` is the list of events actually used to generate this body --
    used only to update the sent-log on success. Returns True on success,
    False on any failure (missing config, connection, auth, or send
    error). Never raises.
    """
    subject = f"Volta Weekly Update — {date.today().isoformat()}"

    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = SENDER_EMAIL
    message["To"] = RECIPIENT_EMAIL

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=15) as server:
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, [RECIPIENT_EMAIL], message.as_string())
    except smtplib.SMTPAuthenticationError:
        logger.exception(
            "send_newsletter: Gmail authentication failed -- check "
            "SENDER_EMAIL/SENDER_APP_PASSWORD (must be an app password)"
        )
        return False
    except smtplib.SMTPException:
        logger.exception("send_newsletter: SMTP error while sending")
        return False
    except (OSError, ssl.SSLError):
        logger.exception("send_newsletter: connection error reaching smtp.gmail.com")
        return False
    except Exception:
        logger.exception("send_newsletter: unexpected failure while sending")
        return False

    logger.info("send_newsletter: email sent to %s", RECIPIENT_EMAIL)
    _mark_as_sent(events)
    return True


if __name__ == "__main__":
    test_body = (
        "This is a test email from send.py.\n\n"
        "If you're reading this, the Gmail SMTP config in .env works."
    )
    test_events = [
        {
            "title": "Test Event",
            "date": "2026-09-20",
            "url": "https://example.com/test-event",
            "source": "Test",
        }
    ]

    success = send_newsletter(test_body, test_events)
    print("Send result:", success)
