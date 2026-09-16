"""
run.py -- orchestration layer for the newsletter pipeline.

build_draft() is the single place that wires collect.py -> generate.py
together, so both the CLI entry point below and preview.py (the Streamlit
UI) share one implementation instead of each re-running the same steps.

CLI usage:
    python run.py            # preview only: prints the draft, sends nothing
    python run.py --send     # preview, then asks to confirm before sending
"""

import argparse

from collect import dedupe_and_filter, fetch_events
from generate import generate_newsletter
from send import send_newsletter


def build_draft() -> tuple:
    """
    Fetch this week's new events and generate the newsletter body.

    Pure logic, no printing or user interaction -- safe to call from a UI.
    Returns (body, events): the generated email body, and the exact list
    of events used to generate it (for send.py's later state write-back).
    """
    raw_events = fetch_events()
    new_events = dedupe_and_filter(raw_events)
    body = generate_newsletter(new_events)
    return body, new_events


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build (and optionally send) this week's newsletter.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="After previewing, ask for confirmation and actually send the email.",
    )
    args = parser.parse_args()

    try:
        body, events = build_draft()
    except Exception as exc:
        print(f"Failed to build draft: {exc}")
        return

    print(f"Fetched {len(events)} new event(s).\n")
    print("--- Draft ---")
    print(body)
    print("--- End of draft ---\n")

    if not args.send:
        return

    answer = input("Confirm send? (y/n): ").strip().lower()
    if answer != "y":
        print("Cancelled -- nothing sent.")
        return

    success = send_newsletter(body, events)
    print("Sent successfully." if success else "Send failed -- see log output above.")


if __name__ == "__main__":
    _main()
