from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:  # pragma: no cover - optional dependency fallback
    st_autorefresh = None

ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "logs" / "console_feed.jsonl"
MODE_PATH = ROOT / "config" / "mode.txt"

RELATIONSHIP_COLORS = {
    "family": "#2e7d32",
    "friend": "#1565c0",
    "professional": "#6a1b9a",
    "unknown": "#6b7280",
    "group": "#6b7280",
}


def read_mode() -> str:
    try:
        text = MODE_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "DRY_RUN"

    value = text.upper().strip()
    return value if value in {"DRY_RUN", "LIVE"} else "DRY_RUN"


def load_logs() -> list[dict]:
    if not LOG_PATH.exists():
        return []

    entries: list[dict] = []

    with LOG_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)

    entries = [entry for entry in entries if isinstance(entry, dict)]
    return entries[-20:][::-1]


def render_relationship_badge(relationship: str) -> None:
    rel = str(relationship or "unknown").lower()
    color = RELATIONSHIP_COLORS.get(rel, "#6b7280")
    st.markdown(
        f"""
        <span style="
            display: inline-block;
            background-color: {color};
            color: white;
            border-radius: 999px;
            padding: 0.25rem 0.7rem;
            font-size: 0.8rem;
            font-weight: 600;
            line-height: 1.2;
            margin-right: 0.5rem;
        ">{rel}</span>
        """,
        unsafe_allow_html=True,
    )


def render_trace_item(item: object) -> None:
    if isinstance(item, dict):
        their_message = item.get("their_message") or item.get("message") or item.get("text") or "No excerpt available"
        my_reply = item.get("my_reply") or item.get("reply")
        distance = item.get("distance")

        st.markdown(f"**Past message:**")
        st.code(their_message, language="text")
        if my_reply:
            st.markdown(f"**Likely reply:**")
            st.code(my_reply, language="text")
        if distance is not None:
            st.caption(f"Distance: {distance}")
        return

    if isinstance(item, str):
        st.code(item, language="text")
        return

    st.write(item)


st.set_page_config(page_title="WhatsApp Console", page_icon="💬", layout="wide")

if st_autorefresh is not None:
    st_autorefresh(interval=2000, key="console_live_feed")

st.title("WhatsApp live decision feed")

mode_value = read_mode()
with st.sidebar:
    st.subheader("Session mode")
    st.markdown(f"**{mode_value}**")

    log_entries = load_logs()
    total_messages = len(log_entries)
    total_replies = sum(1 for entry in log_entries if str(entry.get("decision", "ignore")).lower() == "reply")

    st.subheader("Metrics")
    st.metric("Total messages processed", total_messages)
    st.metric("Total replies sent", total_replies)

if not log_entries:
    st.info("waiting for first message...")
    st.stop()

for entry in log_entries:
    timestamp = entry.get("timestamp", "unknown")
    relationship = str(entry.get("relationship", "unknown")).lower()
    decision = str(entry.get("decision", "ignore")).lower()
    reason = entry.get("reason", "no reason provided")
    reply = entry.get("reply")
    retrieval_trace = entry.get("retrieval_trace") or []

    with st.container():
        st.markdown("---")
        cols = st.columns([2, 1, 1])
        with cols[0]:
            st.caption(timestamp)
        with cols[1]:
            render_relationship_badge(relationship)
        with cols[2]:
            st.markdown(
                f"<span style='color: {'#22c55e' if decision == 'reply' else '#6b7280'}; font-weight: 700;'>{decision}</span>",
                unsafe_allow_html=True,
            )

        st.write(f"Reason: {reason}")

        if reply:
            st.write("Generated reply:")
            st.info(reply)
        else:
            st.write("Generated reply: none")

        with st.expander("retrieval trace"):
            if not retrieval_trace:
                st.write("No retrieval trace available for this message.")
            else:
                for idx, item in enumerate(retrieval_trace, start=1):
                    st.markdown(f"### Trace {idx}")
                    render_trace_item(item)
                    if idx < len(retrieval_trace):
                        st.markdown("---")
