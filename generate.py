"""
generate.py -- Layer 2 of the newsletter pipeline: generation.

Takes the structured, deduped event list produced by collect.py and turns
it into a ready-to-send email body. Calls a local Ollama model once; on
any failure (Ollama not running, model not pulled, timeout, bad response)
it falls back to a deterministic, non-LLM template so a failure here never
crashes the rest of the pipeline (preview.py etc.).
"""

import json
import logging
import re

import requests

from config import OLLAMA_HOST, OLLAMA_MODEL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 120  # local generation on CPU/consumer GPU can be slow

# Appended in code (not left to the model) so it is always present, always
# worded the same way, and never depends on the model following instructions.
DISCLAIMER = (
    "This newsletter is put together automatically and has not been "
    "fact-checked line by line -- if anything looks off, the linked source "
    "is the one to trust."
)

# Shown when there are no events at all. Fully static, no API call.
EMPTY_EVENTS_NEWSLETTER = (
    "Hi Volta community,\n\n"
    "No new updates to share this week -- nothing new came in from our "
    "sources this time around. We'll be back next week with fresh news.\n\n"
    f"{DISCLAIMER}"
)

SYSTEM_PROMPT = f"""You write a short, casual email newsletter for the Volta \
startup community in Halifax / Atlantic Canada.

You will be given a JSON list of events. Each item has exactly these \
fields: "title", "date", "url", "source".

Hard rules, no exceptions:

1. ONLY use information that is literally present in the JSON you are \
given: "title", "date", "url", "source" -- nothing else exists. Do not \
invent, guess, or add ANY detail that is not one of those four fields -- \
no made-up names, amounts, speakers, locations, agenda, or backstory, and \
no describing what will happen at the event or who it's for beyond what \
the title itself literally says. A title like "AI Showcase and Mixer" \
does NOT tell you what will be showcased, who mixes, or that there will \
be "presentations and discussions" -- do not add any of that. If you \
would not know a detail just from reading the bare title and date out \
loud, leave it out.

2. Every single event you mention must be immediately followed by its \
"url" from the data, written out as plain text, so the reader can click \
through to the original source. Never state a fact without its link \
right next to it. Never write a link that isn't one of the "url" values \
you were given. Vary how you introduce the link from item to item -- do \
NOT reuse the exact same connecting phrase for every single event (e.g. \
don't write "at this event:" before every link). Mix it up naturally, \
for example: "Details and tickets: <url>", "More here: <url>", "You can \
check it out at <url>", "Link: <url>", or just dropping the bare URL at \
the end of the sentence. Pick whatever reads most naturally for each \
line, but don't let any one phrase become a repeated template.

3. Do not summarize, editorialize, or add commentary that goes beyond \
what the title/date tells you. It's fine to lightly group or introduce \
items (e.g. "a couple of things coming up:") but never invent why \
something matters or what will happen at it.

4. Plain text only. This email client does NOT render Markdown. Never \
use **bold**, *italics*, # headings, [text](url) link syntax, or \
<url>-with-angle-brackets syntax anywhere in your output. A URL must \
appear as bare plain text with no surrounding punctuation of any kind \
(no <, >, [, ], (, ) around it) -- just the raw "https://..." characters. \
Using any Markdown syntax is a hard failure.

Tone and audience:
- The whole Volta community reads this, not a specific segment -- keep it \
general-audience.
- Friendly, casual, like a quick update from a colleague. NOT a formal \
press release or corporate announcement. Short sentences, no marketing \
fluff, no exclamation-point-per-line hype.
- Avoid repeating the exact same sentence structure for every event in a \
row (e.g. always "Title on Date, link"). Vary sentence shape a little \
across the list so it reads like it was written by a person, not \
generated from a fixed template.
- Plain text email body. A short greeting at the top is fine.

Do not add any disclaimer, "automated content" notice, or fact-check \
caveat yourself -- that line is appended separately after your output. \
Do not sign off at all -- no "Best," no team name, no person's name, no \
organization name. End the email right after the last event with no \
closing line.
"""


_MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\[\]]*\]\((https?://[^\s()]+)\)")
_WRAPPED_URL_PATTERN = re.compile(r"[<\[(](https?://[^\s<>\[\]()]+)[>\])]")


def _strip_url_wrapping(body: str) -> str:
    """
    Remove punctuation local models like to wrap around URLs
    (<url>, [url], (url), or a full [text](url) / [url](url) markdown
    link) -- plain text email shouldn't show those chars.

    The markdown-link pattern is collapsed first: stripping "[" and "("
    wraps independently on "[url](url)" would otherwise leave the URL
    doubled up (each wrapper stripped to a bare URL, concatenated back to
    back with nothing between them).
    """
    body = _MARKDOWN_LINK_PATTERN.sub(r"\1", body)
    body = _WRAPPED_URL_PATTERN.sub(r"\1", body)
    return body


def _strip_trailing_signoff(body: str) -> str:
    """
    Drop any trailing lines after the last event's URL.

    Local models are unreliable at following the "don't sign off"
    instruction -- rather than fight that in the prompt, enforce it here:
    nothing meaningful can follow the last source link, so anything after
    it (a "Best," line, a made-up team name, etc.) is cut.
    """
    lines = body.rstrip().split("\n")
    last_url_line = -1
    for i, line in enumerate(lines):
        if "http://" in line or "https://" in line:
            last_url_line = i
    if last_url_line == -1:
        return body.strip()
    return "\n".join(lines[: last_url_line + 1]).strip()


def _fallback_newsletter(events: list) -> str:
    """Deterministic, non-LLM template. Used whenever the API call fails."""
    lines = ["Hi Volta community,", "", "Here's what's new this week:", ""]
    for event in events:
        title = event.get("title", "(untitled)")
        date = event.get("date", "")
        url = event.get("url", "")
        lines.append(f"- {title} ({date}): {url}")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def generate_newsletter(events: list) -> str:
    """
    Turn a list of event dicts into a ready-to-send newsletter body.

    Each event dict has: title, date, url, source. Returns the empty-state
    message with no API call if `events` is empty. On any API failure,
    falls back to a deterministic template instead of raising.
    """
    if not events:
        return EMPTY_EVENTS_NEWSLETTER

    try:
        events_json = json.dumps(events, ensure_ascii=False, indent=2)

        response = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Here is this week's event list as JSON:\n\n"
                            f"{events_json}\n\n"
                            "Write the newsletter body now."
                        ),
                    },
                ],
                "stream": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        body = response.json().get("message", {}).get("content", "").strip()

        if not body:
            raise ValueError("Ollama returned an empty response")

        body = _strip_url_wrapping(body)
        body = _strip_trailing_signoff(body)
        return f"{body}\n\n{DISCLAIMER}"

    except requests.exceptions.ConnectionError:
        logger.exception(
            "generate_newsletter: could not reach Ollama at %s -- is `ollama serve` running?",
            OLLAMA_HOST,
        )
    except requests.exceptions.Timeout:
        logger.exception("generate_newsletter: Ollama request timed out")
    except requests.exceptions.HTTPError:
        logger.exception(
            "generate_newsletter: Ollama returned an error status -- "
            "is model '%s' pulled? (ollama pull %s)",
            OLLAMA_MODEL,
            OLLAMA_MODEL,
        )
    except Exception:
        logger.exception("generate_newsletter: unexpected failure, using fallback")

    return _fallback_newsletter(events)


if __name__ == "__main__":
    fake_events = [
        {
            "title": "AI Showcase and Mixer",
            "date": "2026-09-16",
            "url": "https://www.eventbrite.ca/e/ai-showcase-and-mixer-tickets-1995680744830",
            "source": "Volta",
        },
        {
            "title": "Vibe Coding Meetup",
            "date": "2026-09-21",
            "url": "https://www.eventbrite.ca/e/vibe-coding-meetup-tickets-1998361732737",
            "source": "Eventbrite",
        },
        {
            "title": "Dal Demo Day 2026",
            "date": "2026-10-06",
            "url": "https://www.eventbrite.ca/e/dal-demo-day-2026-tickets-1994237235254",
            "source": "Eventbrite",
        },
    ]

    print("=== Newsletter with sample events ===\n")
    print(generate_newsletter(fake_events))

    print("\n\n=== Newsletter with no events ===\n")
    print(generate_newsletter([]))
