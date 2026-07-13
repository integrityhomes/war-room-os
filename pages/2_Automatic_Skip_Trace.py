from __future__ import annotations

from datetime import datetime, timezone
import hashlib

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Automatic Skip Trace", page_icon="🔎", layout="wide")

SHEET_ID = "1c3F6mwJwN-EnCKeTxw16f2EfcEAxh4H6WDQPDVkyPrc"
SHEET_GID = "0"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?gid={SHEET_GID}#gid={SHEET_GID}"


def clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def get_secret(name: str, default: str = "") -> str:
    try:
        return clean_text(st.secrets.get(name, default))
    except Exception:
        return default


def safe_value(value):
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def lead_key(row: pd.Series) -> str:
    raw = "|".join(
        [
            clean_text(row.get("seller_name", "")),
            clean_text(row.get("property_address", "")),
            clean_text(row.get("mailing_address", "")),
        ]
    ).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def send_to_webhook(url: str, row: pd.Series) -> tuple[bool, str]:
    payload = {column: safe_value(row.get(column, "")) for column in row.index}
    payload.update(
        {
            "automation_action": "RUN_SKIP_TRACE",
            "source_system": "War Room OS",
            "requested_at_utc": datetime.now(timezone.utc).isoformat(),
            "handoff_rule": "Skiptrace only. Do not text or call until returned phones are reviewed and approved.",
            "google_sheet_id": SHEET_ID,
            "google_sheet_gid": SHEET_GID,
            "google_sheet_url": SHEET_URL,
            "google_sheet_name": "War Room Skip Trace Queue",
            "google_sheet_tab": "Sheet1",
            "required_return_fields": [
                "lead_key",
                "seller_name",
                "property_address",
                "mailing_address",
                "phone_1",
                "phone_2",
                "phone_3",
                "phone_type",
                "phone_confidence",
                "email_1",
                "email_2",
                "skiptrace_source",
                "skiptrace_date",
                "dnc_flag",
                "no_phone_found",
                "next_xleads_action",
            ],
        }
    )
    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code in {200, 201, 202}:
            return True, "Sent successfully"
        return False, f"Webhook returned {response.status_code}: {response.text[:250]}"
    except Exception as exc:
        return False, str(exc)


st.title("War Room OS")
st.subheader("Automatic Skip Trace")
st.write(
    "This page sends every lead marked SKIP_TRACE directly to the existing Zapier webhook. "
    "Zapier writes requests and returned contact data into the connected War Room Skip Trace Queue sheet."
)
st.caption(f"Connected sheet: {SHEET_ID} | tab: Sheet1")

webhook_url = get_secret("SKIPTRACE_WEBHOOK_URL", get_secret("ZAPIER_WEBHOOK_URL"))

if webhook_url:
    st.success("Zapier skip-trace webhook is configured.")
else:
    st.error("The webhook secret is missing. Add SKIPTRACE_WEBHOOK_URL or ZAPIER_WEBHOOK_URL in Streamlit secrets.")
    st.stop()

if "scored_df" not in st.session_state:
    st.warning("Run Intelligent Lead Ranking on the main Seller Lead Command page first.")
    st.stop()

scored_df = st.session_state["scored_df"].copy()
required_columns = {"xleads_action", "duplicate_primary"}
if not required_columns.issubset(scored_df.columns):
    st.error("The scored data is missing required skip-trace fields. Re-run Intelligent Lead Ranking.")
    st.stop()

queue = scored_df[
    scored_df["xleads_action"].astype(str).eq("SKIP_TRACE")
    & scored_df["duplicate_primary"].astype(bool)
].copy()

if queue.empty:
    st.success("No leads need skip tracing in this upload.")
    st.stop()

queue["lead_key"] = queue.apply(lead_key, axis=1)

sent_keys = set(st.session_state.get("skiptrace_sent_keys", []))
unsent = queue[~queue["lead_key"].isin(sent_keys)].copy()

col1, col2, col3 = st.columns(3)
col1.metric("Waiting for skip trace", len(queue))
col2.metric("Already sent this session", len(queue) - len(unsent))
col3.metric("Ready to send now", len(unsent))

preview_columns = [
    column
    for column in [
        "seller_name",
        "property_address",
        "mailing_address",
        "lead_score",
        "missing_information",
        "risk_flags",
    ]
    if column in unsent.columns
]

if not unsent.empty:
    st.dataframe(unsent[preview_columns].head(100), use_container_width=True, hide_index=True)

st.caption("One click sends all unsent records to Zapier and prevents duplicate sends during this session.")

if st.button("Run Automatic Skip Trace", type="primary", disabled=unsent.empty):
    results: list[dict] = []
    progress = st.progress(0)
    total = len(unsent)

    for position, (_, row) in enumerate(unsent.iterrows(), start=1):
        success, message = send_to_webhook(webhook_url, row)
        key = row["lead_key"]
        if success:
            sent_keys.add(key)
        results.append(
            {
                "seller_name": row.get("seller_name", ""),
                "property_address": row.get("property_address", ""),
                "success": success,
                "message": message,
            }
        )
        progress.progress(position / total)

    st.session_state["skiptrace_sent_keys"] = sorted(sent_keys)
    result_df = pd.DataFrame(results)
    successful = int(result_df["success"].sum()) if not result_df.empty else 0
    failed = len(result_df) - successful

    if failed == 0:
        st.success(f"All {successful} skip-trace requests were sent to Zapier.")
    else:
        st.warning(f"Sent {successful}; {failed} failed. Review the audit table below.")

    st.dataframe(result_df, use_container_width=True, hide_index=True)
    st.download_button(
        "Download Skip Trace Audit Log",
        result_df.to_csv(index=False).encode("utf-8"),
        "war_room_skiptrace_audit_log.csv",
        "text/csv",
    )
