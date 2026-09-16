"""
collect.py -- Layer 1 of the newsletter pipeline: collection + dedupe.

Pure deterministic scraping and set-comparison logic. No LLM calls here.

Data sources (both expose events as schema.org JSON-LD, so we parse that
instead of fragile CSS selectors):
  - Volta events page:        https://voltaeffect.com/events
  - Eventbrite Halifax tech/startup category page:
        https://www.eventbrite.com/d/canada--halifax/tech-startup/
"""

import json
import logging
import re
from pathlib import Path

import requests

from config import EVENTBRITE_HALIFAX_TECH_URL, VOLTA_EVENTS_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent / "state"
STATE_FILE = STATE_DIR / "sent_log.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 10  # seconds

JSONLD_PATTERN = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)


def _extract_jsonld_blocks(html: str) -> list:
    """
    Return every JSON-LD object on the page, already json.loads()'d.

    A single <script> tag may hold one object or a list of objects, so
    flatten lists into individual entries.
    """
    blocks = []
    for raw in JSONLD_PATTERN.findall(html):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            blocks.extend(parsed)
        else:
            blocks.append(parsed)
    return blocks


def _iso_date_only(value: str) -> str:
    """Normalize an ISO 8601 datetime/date string down to YYYY-MM-DD."""
    if not value:
        return ""
    return value[:10]


def _fetch_volta_events() -> list:
    """Scrape Volta's events page via its embedded JSON-LD ItemList."""
    events = []
    resp = requests.get(VOLTA_EVENTS_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    for block in _extract_jsonld_blocks(resp.text):
        if isinstance(block, dict) and block.get("@type") == "ItemList":
            for list_item in block.get("itemListElement", []):
                item = list_item.get("item", {})
                if item.get("@type") != "Event":
                    continue
                events.append(
                    {
                        "title": item.get("name", ""),
                        "date": _iso_date_only(item.get("startDate", "")),
                        "url": item.get("url", ""),
                        "source": "Volta",
                    }
                )
    return events


def _fetch_eventbrite_halifax_tech() -> list:
    """Scrape Eventbrite's Halifax tech/startup category page via its JSON-LD ItemList."""
    events = []
    resp = requests.get(
        EVENTBRITE_HALIFAX_TECH_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()

    for block in _extract_jsonld_blocks(resp.text):
        if isinstance(block, dict) and block.get("@type") == "ItemList":
            for list_item in block.get("itemListElement", []):
                item = list_item.get("item", {})
                if item.get("@type") != "Event":
                    continue
                events.append(
                    {
                        "title": item.get("name", ""),
                        "date": _iso_date_only(item.get("startDate", "")),
                        "url": item.get("url", ""),
                        "source": "Eventbrite",
                    }
                )
    return events


def fetch_events() -> list:
    """
    Fetch raw events from all configured sources.

    Pulls clean facts only -- no rewriting, no inference. Each source is
    isolated: if one fails (network error, timeout, changed page structure),
    that source contributes an empty list instead of crashing the run.
    """
    all_events = []

    for name, fetch_fn in (
        ("Volta", _fetch_volta_events),
        ("Eventbrite", _fetch_eventbrite_halifax_tech),
    ):
        try:
            source_events = fetch_fn()
            logger.info("Fetched %d event(s) from %s", len(source_events), name)
            all_events.extend(source_events)
        except Exception:
            logger.exception("Failed to fetch events from %s", name)

    return all_events


def _event_key(event: dict) -> str:
    """Unique identity for an event: prefer its URL, else title+date."""
    url = event.get("url", "").strip()
    if url:
        return url
    return f"{event.get('title', '').strip()}|{event.get('date', '').strip()}"


def _load_sent_log() -> set:
    if not STATE_FILE.exists():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text("[]", encoding="utf-8")
        return set()

    try:
        with STATE_FILE.open(encoding="utf-8") as f:
            sent_keys = json.load(f)
        return set(sent_keys)
    except (json.JSONDecodeError, OSError):
        logger.exception("Could not read %s, treating log as empty", STATE_FILE)
        return set()


def dedupe_and_filter(events: list) -> list:
    """
    Filter out events already recorded in state/sent_log.json.

    Exact-match dedupe only (by URL, or title+date when no URL) -- no
    semantic/fuzzy matching.
    """
    sent_keys = _load_sent_log()

    new_events = []
    seen_this_run = set()
    for event in events:
        key = _event_key(event)
        if key in sent_keys or key in seen_this_run:
            continue
        seen_this_run.add(key)
        new_events.append(event)

    return new_events


if __name__ == "__main__":
    print("Fetching events...")
    raw_events = fetch_events()
    print(f"\nFetched {len(raw_events)} total event(s):")
    for e in raw_events:
        print(f"  - [{e['source']}] {e['date']} | {e['title']} | {e['url']}")

    print("\nFiltering against state/sent_log.json...")
    new_events = dedupe_and_filter(raw_events)
    print(f"\n{len(new_events)} new event(s) after dedupe:")
    for e in new_events:
        print(f"  - [{e['source']}] {e['date']} | {e['title']} | {e['url']}")
