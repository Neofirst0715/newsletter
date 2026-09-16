"""
config.py -- single source of truth for configuration.

Loads .env via python-dotenv and exposes every setting as a module-level
constant. Every other file imports its config from here (e.g.
`from config import SENDER_EMAIL`) instead of touching os.getenv or
hardcoding values directly.

Fails fast at import time: if any required variable is missing or empty,
this module raises RuntimeError immediately, naming exactly which
variable(s) are missing -- so a misconfigured .env breaks loudly at
startup instead of surfacing as a mysterious None deep inside collect.py,
generate.py, or send.py.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- generate.py: local Ollama model ---
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")  # optional, has a default
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")  # optional, has a default

# --- send.py: Gmail SMTP ---
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD")
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL")

# --- collect.py: data source URLs ---
VOLTA_EVENTS_URL = os.getenv("VOLTA_EVENTS_URL")
EVENTBRITE_HALIFAX_TECH_URL = os.getenv("EVENTBRITE_HALIFAX_TECH_URL")

_REQUIRED = {
    "SENDER_EMAIL": SENDER_EMAIL,
    "SENDER_APP_PASSWORD": SENDER_APP_PASSWORD,
    "RECIPIENT_EMAIL": RECIPIENT_EMAIL,
    "VOLTA_EVENTS_URL": VOLTA_EVENTS_URL,
    "EVENTBRITE_HALIFAX_TECH_URL": EVENTBRITE_HALIFAX_TECH_URL,
}

_missing = [name for name, value in _REQUIRED.items() if not value]
if _missing:
    raise RuntimeError(
        "Missing required environment variable(s): "
        f"{', '.join(_missing)}. Set them in .env (see .env.example for the expected keys)."
    )
