from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from lead_intelligence import (
    DEFAULT_TARGET_STATES,
    clean_text,
    run_greatness_test,
    score_dataframe,
)

st.set_page_config(page_title="War Room OS", page_icon="🏠", layout="wide")
APP_TITLE = "War Room OS"
MODULE_TITLE = "Seller Lead Command — Intelligence Layer"
DEFAULT_TIMEZONE = "America/Chicago"
PREVIEW_LIMIT = 100


def get_secret(name: str, default: str = "") -> str:
    try:
        return clean_text(st.secrets.get(name, default))
    except Exception:
        return default


ZAPIER_WEBHOOK_URL = get_secret("ZAPIER_WEBHOOK_URL")
SKIPTRACE_WEBHOOK_URL = get_secret("SKIPTRACE_WEBHOOK_URL", ZAPIER_WEBHOOK_URL)


def find_column(df: pd.DataFrame, options: list[str]) -> str | None:
    normalized = {str(column).strip().lower(): column for column in df.columns}
    for option in options:
        match = normalized.get(option.strip().lower())
        if match is not None:
            return match
    return None


def series_from(df: pd.DataFrame, options: list[str], default: str = "") -> pd.Series:
    column = find_column(df, options)
    if column is None:
        return pd.Series([default] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str)


def combine_address(street: str, city: str, state: str, postal: str) -> str:
    parts = [clean_text(street), clean_text(city), clean_text(state), clean_text(postal)]
    return ", ".join(part for part in parts if part and part.lower() not in {"none", "nan"})


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    first = series_from(df, ["FirstName", "First Name", "first_name", "seller_first_name"])
    last = series_from(df, ["LastName", "Last Name", "last_name", "seller_last_name"])
    full_name = series_from(df, ["seller_name", "Seller Name", "Name", "Owner", "OwnerName", "Owner Name", "FullName", "Full Name"])
    df["seller_name"] = full_name.where(full_name.str.strip().ne(""), (first + " " + last).str.strip())

    # XLeads/Leadpipes exports often return phone_1/phone_2 or Phone 1/Phone 2. Count any of them as a usable phone.
    df["phone"] = series_from(df, [
        "phone", "Phone", "PhoneNumber", "Phone Number", "Mobile", "MobilePhone",
        "RecipientPhone", "OwnerPhone", "PrimaryPhone", "Primary Phone", "phone1", "phone_1", "Phone 1",
        "phone2", "phone_2", "Phone 2", "phone3", "phone_3", "Phone 3",
        "ContactPhone", "Contact1Phone_1", "Contact1Phone1", "Contact1 Phone 1",
        "Contact1Phone_2", "Contact1Phone2", "Contact1 Phone 2",
        "Contact2Phone_1", "Contact2Phone1", "Contact2 Phone 1",
    ])
    df["phone_1"] = series_from(df, ["phone_1", "Phone 1", "phone1", "Contact1Phone_1", "Contact1 Phone 1"])
    df["phone_2"] = series_from(df, ["phone_2", "Phone 2", "phone2", "Contact1Phone_2", "Contact1 Phone 2"])
    df["phone_3"] = series_from(df, ["phone_3", "Phone 3", "phone3", "Contact2Phone_1", "Contact2 Phone 1"])

    df["email"] = series_from(df, ["email", "Email", "EmailAddress", "Email Address", "RecipientEmail", "OwnerEmail", "email_1", "Email 1"])
    df["email_1"] = series_from(df, ["email_1", "Email 1", "Email"])
    df["email_2"] = series_from(df, ["email_2", "Email 2"])

    df["seller_message"] = series_from(df, [
        "seller_message", "message", "reply", "seller_reply", "last_message",
        "sms", "body", "Text", "Conversation", "Last Inbound Message",
    ])
    df["call_transcript"] = series_from(df, ["call_transcript", "Call Transcript", "Transcript", "AI Call Transcript", "Voice Transcript", "Conversation Transcript"])
    df["call_summary"] = series_from(df, ["call_summary", "Call Summary", "AI Call Summary", "Voice Summary", "Summary"])
    df["call_disposition"] = series_from(df, ["call_disposition", "Call Disposition", "Disposition", "AI Disposition", "Call Result"])
    df["ai_summary"] = series_from(df, ["ai_summary", "AI Summary", "AI Notes", "Qualification Summary"])
    df["notes"] = series_from(df, ["notes", "Notes", "Lead Notes", "Seller Notes"])
    df["motivation_detail"] = series_from(df, ["motivation", "Motivation", "Seller Motivation", "Why Selling"])
    df["timeline_detail"] = series_from(df, ["timeline", "Timeline", "Selling Timeline", "Timeframe"])
    df["condition_detail"] = series_from(df, ["condition", "Condition", "Property Condition", "Repairs Needed"])
    df["occupancy_detail"] = series_from(df, ["occupancy", "Occupancy", "Property Occupancy", "Vacancy Status"])
    df["price_detail"] = series_from(df, ["asking_price", "Asking Price", "Seller Price", "Price Expectation"])
    df["campaign_name"] = series_from(df, ["campaign_name", "campaign", "Campaign", "ListName", "List Name", "SourceList"], "XLeads Export")
    df["source"] = series_from(df, ["source", "Source", "Lead Source"], "XLeads")
    df["seller_timezone"] = series_from(df, ["seller_timezone", "timezone", "time_zone", "TimeZone"], DEFAULT_TIMEZONE)

    df["property_street"] = series_from(df, ["PropertyAddress", "Property Address", "property_address", "SiteAddress", "SitusAddress"])
    df["property_city"] = series_from(df, ["PropertyCity", "Property City", "property_city", "SiteCity", "SitusCity"])
    df["property_state"] = series_from(df, ["PropertyState", "Property State", "property_state", "SiteState", "SitusState"])
    df["property_zip"] = series_from(df, ["PropertyPostalCode", "Property Zip", "PropertyZip", "property_zip", "SiteZip", "SitusZip"])
    df["mailing_street"] = series_from(df, ["RecipientAddress", "MailingAddress", "Mailing Address", "OwnerAddress", "Owner Address"])
    df["mailing_city"] = series_from(df, ["RecipientCity", "MailingCity", "Mailing City", "OwnerCity", "Owner City"])
    df["mailing_state"] = series_from(df, ["RecipientState", "MailingState", "Mailing State", "OwnerState", "Owner State"])
    df["mailing_zip"] = series_from(df, ["RecipientPostalCode", "MailingZip", "Mailing Zip", "OwnerZip", "Owner Zip"])
    df["property_address"] = df.apply(lambda row: combine_address(row["property_street"], row["property_city"], row["property_state"], row["property_zip"]), axis=1)
    df["mailing_address"] = df.apply(lambda row: combine_address(row["mailing_street"], row["mailing_city"], row["mailing_state"], row["mailing_zip"]), axis=1)
    return df.copy()


def detect_file_mode(df: pd.DataFrame) -> str:
    engagement_columns = ["seller_message", "call_transcript", "call_summary", "call_disposition", "ai_summary"]
    engagement_count = sum(df[column].astype(str).str.strip().replace("nan", "").ne("").sum() for column in engagement_columns)
    return "Seller Replies" if engagement_count > 0 else "Raw XLeads Property List"


def inside_calling_hours(timezone_name: str) -> bool:
    try:
        now = datetime.now(ZoneInfo(clean_text(timezone_name) or DEFAULT_TIMEZONE))
    except Exception:
        now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    return 8 <= now.hour < 21


def ensure_unique_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.columns.is_unique:
        return df.copy()
    output = pd.DataFrame(index=df.index)
    for column in dict.fromkeys(str(c) for c in df.columns):
        matches = df.loc[:, [str(c) == column for c in df.columns]]
        if matches.shape[1] == 1:
            output[column] = matches.iloc[:, 0]
            continue
        merged = matches.iloc[:, -1].copy()
        for position in range(matches.shape[1] - 2, -1, -1):
            earlier = matches.iloc[:, position]
            blank = merged.isna() | merged.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null", "<na>"])
            merged = merged.where(~blank, earlier)
        output[column] = merged
    return output.copy()


def display_columns(df: pd.DataFrame, extra: list[str] | None = None) -> list[str]:
    preferred = [
        "call_lane", "call_deadline", "lead_score", "opportunity_score_10", "confidence",
        "seller_name", "phone", "phone_1", "phone_2", "property_address", "seller_message", "call_summary",
        "timeline_bucket", "asking_price_extracted", "motivation", "missing_information",
        "recommended_next_question", "xleads_action", "rei_blackbook_tags", "risk_flags",
    ]
    if extra:
        preferred.extend(extra)
    return [column for column in preferred if column in df.columns]


def safe_table(df: pd.DataFrame, columns: list[str] | None = None, limit: int = PREVIEW_LIMIT) -> pd.DataFrame:
    view = df.copy()
    if columns:
        view = view[[c for c in columns if c in view.columns]].copy()
    if len(view) > limit:
        view = view.head(limit).copy()
    for column in view.columns:
        view[column] = view[column].fillna("").astype(str)
    return view.copy()


def show_table(df: pd.DataFrame, columns: list[str] | None = None, limit: int = PREVIEW_LIMIT) -> None:
    """Render tables as lightweight HTML instead of Streamlit's Arrow table to avoid segfaults."""
    if df.empty:
        st.caption("No records in this queue.")
        return
    if len(df) > limit:
        st.caption(f"Showing first {limit} of {len(df)} records. Use the download button for the full file.")
    view = safe_table(df, columns=columns, limit=limit)
    html = view.to_html(index=False, escape=True)
    st.markdown(
        f"""
        <div style="max-height:520px; overflow:auto; border:1px solid #ddd; border-radius:6px;">
        <style>
        table {{border-collapse: collapse; width: 100%; font-size: 13px;}}
        th, td {{border: 1px solid #ddd; padding: 6px; text-align: left; vertical-align: top;}}
        th {{background: #f7f7f7; position: sticky; top: 0; z-index: 1;}}
        </style>
        {html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def safe_payload_value(value):
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def send_to_webhook(url: str, payload: dict) -> tuple[bool, str]:
    if not url:
        return False, "No webhook URL is saved in Streamlit secrets."
    try:
        response = requests.post(url, json=payload, timeout=30)
        if response.status_code in {200, 201, 202}:
            return True, "Sent successfully."
        return False, f"Webhook returned {response.status_code}: {response.text[:250]}"
    except Exception as exc:
        return False, str(exc)


def send_to_zapier(row: pd.Series) -> tuple[bool, str]:
    if not ZAPIER_WEBHOOK_URL:
        return False, "No ZAPIER_WEBHOOK_URL is saved in Streamlit secrets."
    fields = [
        "seller_name", "phone", "phone_1", "phone_2", "phone_3", "clean_phone", "email", "email_1", "email_2",
        "property_address", "mailing_address", "campaign_name", "source", "seller_message",
        "call_transcript", "call_summary", "call_disposition", "lead_status", "lead_score",
        "opportunity_score_10", "lead_lane", "call_lane", "call_deadline", "must_call", "confidence",
        "motivation", "score_explanation", "recommended_next_step", "recommended_next_question",
        "missing_information", "risk_flags", "reason_codes", "asking_price_extracted", "timeline_bucket",
        "xleads_action", "rei_blackbook_tag", "rei_blackbook_tags", "rei_blackbook_workflow", "summary_note",
    ]
    payload = {field: safe_payload_value(row.get(field, "")) for field in fields}
    payload["phone"] = row.get("clean_phone", row.get("phone", ""))
    payload["automation_action"] = "PUSH_ACTIVE_OPPORTUNITY"
    payload["source_system"] = "War Room OS"
    payload["requested_at_utc"] = datetime.now(timezone.utc).isoformat()
    return send_to_webhook(ZAPIER_WEBHOOK_URL, payload)


def build_skiptrace_queue(scored_df: pd.DataFrame) -> pd.DataFrame:
    skiptrace = scored_df[
        scored_df["xleads_action"].astype(str).eq("SKIP_TRACE")
        & scored_df["duplicate_primary"].astype(bool)
    ].copy()
    if skiptrace.empty:
        return skiptrace
    skiptrace["skiptrace_status"] = "QUEUED_FOR_SKIPTRACE"
    skiptrace["skiptrace_requested_at_utc"] = datetime.now(timezone.utc).isoformat()
    skiptrace["skiptrace_priority"] = skiptrace["lead_score"].rank(method="dense", ascending=False).astype(int)
    skiptrace["skiptrace_reason"] = skiptrace.apply(
        lambda row: " | ".join(
            part for part in [
                clean_text(row.get("lead_status", "")),
                clean_text(row.get("missing_information", "")),
                clean_text(row.get("risk_flags", "")),
                clean_text(row.get("motivation", "")),
            ] if part
        ),
        axis=1,
    )
    return skiptrace.sort_values(["lead_score", "confidence"], ascending=[False, False]).reset_index(drop=True).copy()


def send_skiptrace_to_webhook(row: pd.Series) -> tuple[bool, str]:
    if not SKIPTRACE_WEBHOOK_URL:
        return False, "No SKIPTRACE_WEBHOOK_URL or ZAPIER_WEBHOOK_URL is saved in Streamlit secrets."
    payload = {column: safe_payload_value(row.get(column, "")) for column in row.index}
    payload.update({
        "automation_action": "RUN_SKIP_TRACE",
        "source_system": "War Room OS",
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "handoff_rule": "Skiptrace only. Do not text or call until returned phones are reviewed and approved.",
        "required_return_fields": [
            "seller_name", "property_address", "mailing_address", "phone_1", "phone_2", "phone_3",
            "phone_type", "phone_confidence", "email_1", "email_2", "skiptrace_source", "skiptrace_date",
            "dnc_flag", "no_phone_found", "next_xleads_action",
        ],
    })
    return send_to_webhook(SKIPTRACE_WEBHOOK_URL, payload)


def feedback_template(scored_df: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in [
        "seller_name", "phone", "property_address", "seller_message", "call_lane",
        "lead_score", "reason_codes", "risk_flags",
    ] if column in scored_df.columns]
    template = scored_df[columns].copy()
    template["actual_outcome"] = ""
    template["contract_signed"] = ""
    template["deal_type"] = ""
    template["deal_revenue"] = ""
    template["ranking_was_correct"] = ""
    template["team_notes"] = ""
    return template.copy()


st.title(APP_TITLE)
st.subheader(MODULE_TITLE)
st.write(
    "This is the intelligence layer above XLeads. XLeads handles texting, AI voice calls, and workflows; "
    "this module protects opportunities, ranks the must-call queue, explains every decision, and identifies "
    "what question is still missing."
)

with st.sidebar:
    st.header("Lead Intelligence Settings")
    target_states_text = st.text_input("Target states", value=",".join(DEFAULT_TARGET_STATES))
    target_states = [item.strip().upper() for item in target_states_text.split(",") if item.strip()]
    st.caption("Raw lists outside these states are held for review. Seller replies are still analyzed so a live opportunity is never silently discarded.")
    st.info("AI voice calls require clear seller call permission. Human call tasks remain visible after hours but should be completed in the proper calling window.")
    if SKIPTRACE_WEBHOOK_URL:
        st.success("Skip Trace Queue webhook is configured.")
    else:
        st.warning("Skip Trace Queue webhook is not configured yet. Add SKIPTRACE_WEBHOOK_URL or ZAPIER_WEBHOOK_URL in Streamlit secrets.")

with st.expander("CSV fields this version understands"):
    st.write("It accepts raw XLeads exports, seller SMS replies, AI voice transcripts, call summaries, dispositions, motivation, timeline, condition, occupancy, and price fields. Column names are normalized automatically.")

uploaded_file = st.file_uploader("Upload XLeads CSV", type=["csv"])
if uploaded_file is None:
    st.warning("Upload an XLeads CSV to begin.")
    if st.button("Run built-in greatness test"):
        test_df = run_greatness_test()
        passed = int(test_df["passed"].sum())
        st.metric("Greatness tests passed", f"{passed}/{len(test_df)}")
        show_table(test_df, limit=100)
    st.stop()

try:
    raw_df = pd.read_csv(uploaded_file)
except Exception as exc:
    st.error(f"The CSV could not be read: {exc}")
    st.stop()

normalized_df = normalize_columns(raw_df)
file_mode = detect_file_mode(normalized_df)
st.success(f"Detected file type: {file_mode}")
with st.expander("Preview normalized upload"):
    show_table(normalized_df, limit=30)
    st.write("Detected columns:", list(raw_df.columns))

if st.button("Run Intelligent Lead Ranking", type="primary"):
    with st.spinner("Scoring leads..."):
        scored = score_dataframe(normalized_df, file_mode, target_states=target_states)
        scored = ensure_unique_columns(scored)
        scored["inside_calling_hours"] = scored["seller_timezone"].apply(inside_calling_hours)
        scored["ai_call_allowed"] = scored["ai_call_allowed"] & scored["inside_calling_hours"]
        scored["human_call_task_allowed"] = scored["human_call_task_allowed"] & scored["inside_calling_hours"]
        st.session_state["scored_df"] = scored.copy()
        st.session_state["file_mode"] = file_mode

if "scored_df" not in st.session_state:
    st.stop()

scored_df = ensure_unique_columns(st.session_state["scored_df"]).copy()
file_mode = st.session_state["file_mode"]
total = len(scored_df)

if file_mode == "Seller Replies":
    values = [
        total,
        int((scored_df["call_lane"] == "Call Now").sum()),
        int((scored_df["call_lane"] == "Call Today").sum()),
        int(scored_df["call_lane"].isin(["Keep Qualifying", "Scheduled Follow-Up"]).sum()),
        int((scored_df["call_lane"] == "Human Review").sum()),
        int(scored_df["call_lane"].isin(["Do Not Contact", "Closed / No Call", "Duplicate / Suppress"]).sum()),
    ]
    labels = ["Total", "Call Now", "Call Today", "Qualify / Follow-Up", "Human Review", "Blocked / Closed"]
    for col, label, value in zip(st.columns(6), labels, values):
        col.metric(label, value)
else:
    values = [
        total,
        int((scored_df["lead_status"] == "Priority Campaign Lead").sum()),
        int((scored_df["lead_status"] == "Ready for Campaign").sum()),
        int((scored_df["lead_status"] == "Needs Phone / Skip Trace").sum()),
        int((scored_df["lead_status"] == "Needs Property Data").sum()),
        int(scored_df["human_review_required"].astype(bool).sum()),
    ]
    labels = ["Total Raw Leads", "Priority Campaign", "Ready for Campaign", "Skip Trace", "Needs Property Data", "Review"]
    for col, label, value in zip(st.columns(6), labels, values):
        col.metric(label, value)

tabs = st.tabs([
    "Must Call Queue", "Missed-Opportunity Watch", "Follow-Up", "Compliance",
    "Skip Trace Queue", "Raw Campaign Queue", "All Scored Leads", "Greatness Test",
    "Learning Loop", "Push / Export",
])

with tabs[0]:
    st.write("### Must Call Queue")
    queue = scored_df[
        scored_df["must_call"].astype(bool)
        & scored_df["duplicate_primary"].astype(bool)
        & ~scored_df["opt_out_detected"].astype(bool)
        & ~scored_df["wrong_number_detected"].astype(bool)
    ].copy().sort_values(["call_priority_rank", "lead_score", "confidence"], ascending=[True, False, False])
    show_table(queue, display_columns(queue))
    st.download_button("Download Must Call Queue", queue.to_csv(index=False).encode("utf-8"), "war_room_must_call_queue.csv", "text/csv", key="download_must_call")

with tabs[1]:
    st.write("### Missed-Opportunity Watch")
    watch = scored_df[
        scored_df["human_review_required"].astype(bool)
        | scored_df["other_property_opportunity"].astype(bool)
        | scored_df["price_expectation_review"].astype(bool)
        | scored_df["risk_flags"].astype(str).str.contains("OWNERSHIP_VERIFY|PROPERTY_SOLD|TEXT_ONLY", regex=True, na=False)
    ].copy()
    show_table(watch, display_columns(watch))

with tabs[2]:
    st.write("### Follow-Up and Next Questions")
    follow_up = scored_df[scored_df["call_lane"].isin(["Keep Qualifying", "Scheduled Follow-Up", "Human Review"])].copy()
    show_table(follow_up, display_columns(follow_up))

with tabs[3]:
    st.write("### Compliance and Call Permissions")
    columns = [column for column in [
        "seller_name", "phone", "phone_1", "phone_2", "property_address", "seller_message", "call_lane", "call_permission",
        "inside_calling_hours", "ai_call_allowed", "human_call_task_allowed", "opt_out_detected",
        "wrong_number_detected", "duplicate_flag", "duplicate_primary", "risk_flags", "xleads_action",
    ] if column in scored_df.columns]
    show_table(scored_df, columns)

with tabs[4]:
    st.write("### Skip Trace Queue")
    st.caption("Records marked `SKIP_TRACE`. This does not text or call; it only prepares or sends skiptrace requests.")
    skiptrace_queue = build_skiptrace_queue(scored_df)
    st.metric("Leads waiting for skiptrace", len(skiptrace_queue))
    if skiptrace_queue.empty:
        st.success("No leads need skiptrace in this upload.")
    else:
        priority_cols = [column for column in [
            "skiptrace_priority", "lead_score", "seller_name", "property_address", "mailing_address",
            "phone_1", "phone_2", "email", "lead_status", "missing_information", "risk_flags", "skiptrace_reason", "xleads_action",
        ] if column in skiptrace_queue.columns]
        show_table(skiptrace_queue, priority_cols)
        st.download_button("Download Clean Skip Trace Queue CSV", skiptrace_queue.to_csv(index=False).encode("utf-8"), "war_room_skiptrace_queue.csv", "text/csv", key="download_skiptrace_queue")
        st.warning("Send a small batch first. This avoids Zapier limits and keeps Streamlit stable.")
        max_records = int(st.number_input("Max skiptrace records to send now", min_value=1, max_value=len(skiptrace_queue), value=min(5, len(skiptrace_queue)), step=1))
        if st.button("Send Skip Trace Batch to Webhook", type="primary"):
            batch = skiptrace_queue.head(max_records).copy()
            results = []
            progress = st.progress(0)
            for idx, (_, row) in enumerate(batch.iterrows(), start=1):
                success, message = send_skiptrace_to_webhook(row)
                results.append({
                    "seller_name": row.get("seller_name", ""),
                    "property_address": row.get("property_address", ""),
                    "lead_score": row.get("lead_score", ""),
                    "success": success,
                    "message": message,
                })
                progress.progress(idx / len(batch))
            result_df = pd.DataFrame(results)
            show_table(result_df, limit=100)
            st.download_button("Download Skip Trace Send Audit Log", result_df.to_csv(index=False).encode("utf-8"), "war_room_skiptrace_audit_log.csv", "text/csv", key="download_skiptrace_audit_log")

with tabs[5]:
    st.write("### Raw Campaign Queue")
    if file_mode == "Raw XLeads Property List":
        campaign = scored_df[scored_df["lead_status"].isin(["Priority Campaign Lead", "Ready for Campaign"]) & scored_df["duplicate_primary"].astype(bool)].copy()
        show_table(campaign, display_columns(campaign, ["lead_status"]))
        st.download_button("Download XLeads Campaign Queue", campaign.to_csv(index=False).encode("utf-8"), "war_room_xleads_campaign_queue.csv", "text/csv", key="download_campaign")
    else:
        st.info("This upload contains seller engagement, so the call and follow-up queues are the correct views.")

with tabs[6]:
    st.write("### All Scored Leads")
    show_table(scored_df, limit=50)
    st.download_button("Download All Scored Leads", scored_df.to_csv(index=False).encode("utf-8"), "war_room_all_scored_leads.csv", "text/csv", key="download_all")

with tabs[7]:
    st.write("### Built-In Greatness Test")
    if st.button("Run Greatness Test", key="greatness_test_tab"):
        test_df = run_greatness_test()
        passed = int(test_df["passed"].sum())
        failed = len(test_df) - passed
        col1, col2 = st.columns(2)
        col1.metric("Passed", f"{passed}/{len(test_df)}")
        col2.metric("Failed", failed)
        st.success("Every built-in edge-case scenario passed.") if failed == 0 else st.error("One or more edge cases failed. Do not deploy until corrected.")
        show_table(test_df, limit=100)

with tabs[8]:
    st.write("### Closed-Deal Learning Loop")
    template = feedback_template(scored_df)
    st.download_button("Download Team Outcome Feedback Sheet", template.to_csv(index=False).encode("utf-8"), "war_room_outcome_feedback.csv", "text/csv", key="download_feedback")

with tabs[9]:
    st.write("### Push Active Opportunities Through Zapier")
    active = scored_df[
        scored_df["duplicate_primary"].astype(bool)
        & ~scored_df["call_lane"].isin(["Do Not Contact", "Closed / No Call", "Duplicate / Suppress"])
    ].copy()
    show_table(active, display_columns(active), limit=50)
    if st.button("Send Active Opportunities to Zapier / REI BlackBook"):
        results = []
        for _, row in active.iterrows():
            success, message = send_to_zapier(row)
            results.append({
                "seller_name": row.get("seller_name", ""),
                "property_address": row.get("property_address", ""),
                "call_lane": row.get("call_lane", ""),
                "success": success,
                "message": message,
            })
        show_table(pd.DataFrame(results), limit=100)
