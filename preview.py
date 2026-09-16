"""
preview.py -- Layer 4 of the newsletter pipeline: preview / review UI.

Streamlit app with three stages:
  1. Generate this week's draft (runs run.py's build_draft() once, on click)
  2. Review and edit the draft (plain text_area, backed by session_state)
  3. Confirm and send (two-step confirmation, then send.py)

session_state is the source of truth for the draft text and the pending
send confirmation, so editing the text area or any other widget never
re-triggers fetching or generation -- only clicking "Generate this week's
draft" does.
"""

import streamlit as st

from run import build_draft
from send import send_newsletter

st.set_page_config(page_title="Volta Newsletter Preview")

st.title("Volta Newsletter - Draft & Send")

# --- session state defaults (only set if missing; never overwritten on rerun) ---
if "draft_text" not in st.session_state:
    st.session_state.draft_text = ""
if "draft_events" not in st.session_state:
    st.session_state.draft_events = []
if "confirm_pending" not in st.session_state:
    st.session_state.confirm_pending = False

# --- Stage 1: generate draft ---
st.header("1. Generate draft")

if st.button("Generate this week's draft"):
    try:
        with st.spinner("Fetching events and writing newsletter..."):
            body, events = build_draft()
        st.session_state.draft_text = body
        st.session_state.draft_events = events
        st.session_state.confirm_pending = False
        st.success(f"Draft generated from {len(events)} new event(s).")
    except Exception as exc:
        st.error(f"Failed to generate draft: {exc}")

# --- Stage 2: review / edit draft ---
st.header("2. Review & edit")

st.text_area(
    "Newsletter draft (editable)",
    key="draft_text",
    height=400,
    placeholder="Click 'Generate this week's draft' above to create a draft.",
)

# --- Stage 3: confirm & send ---
st.header("3. Send")

has_draft = bool(st.session_state.draft_text.strip())

if st.button("Confirm & Send", disabled=not has_draft):
    st.session_state.confirm_pending = True

if st.session_state.confirm_pending:
    st.warning("Are you sure you want to send this email? This cannot be undone.")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Yes, send it"):
            success = send_newsletter(st.session_state.draft_text, st.session_state.draft_events)
            st.session_state.confirm_pending = False
            if success:
                st.success("Newsletter sent.")
            else:
                st.error("Send failed -- check the terminal log for details.")
    with col_no:
        if st.button("Cancel"):
            st.session_state.confirm_pending = False
