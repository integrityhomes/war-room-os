from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from lead_intelligence import DEFAULT_TARGET_STATES, clean_text, run_greatness_test, score_dataframe

st.set_page_config(page_title="War Room OS", page_icon="🏠", layout="wide")

APP_TITLE = "War Room OS"
MODULE_TITLE = "Seller Lead Command — Intelligence Layer"
DEFAULT_TIMEZONE = "America/Chicago"
PREVIEW_LIMIT = 100


def find_column(df: pd.DataFrame, options: list[str]) -> str | None:
    normalized = {str(column).strip().lower(): column for column in df.columns}
    for option in options:
        if option.strip().lower() in normalized:
            return normalized[option.strip().lower()]
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

    df["seller_message"] = series_from(df, ["seller_message", "message", "reply", "seller_reply", "last_message", "sms", "body", "Text", "Conversation", "Last Inbound Message"])
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
    return df


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
    columns: dict[str, pd.Series] = {}
    for name in dict.fromkeys(str(column) for column in df.columns):
        matches = df.loc[:, [str(column) == name for column in df.columns]]
        merged = matches.iloc[:, -1].copy()
        for position in range(matches.shape[1] - 2, -1, -1):
            earlier = matches.iloc[:, position]
            blank = merged.isna() | merged.astype(str).str.strip().str.lower().isin(["", "nan", "none", "null", "<na>"])
            merged = merged.where(~blank, earlier)
        columns[name] = merged
    return pd.DataFrame(columns, index=df.index)


def show_table(df: pd.DataFrame, columns: list[str] | None = None, limit: int = PREVIEW_LIMIT) -> None:
    if df.empty:
        st.caption("No records in this queue.")
        return
    view = df.copy()
    if columns:
        view = view[[column for column in columns if column in view.columns]].copy()
    if len(view) > limit:
        st.caption(f"Showing first {limit} of {len(view)} records. Download the CSV for the full queue.")
        view = view.head(limit)
    for column in view.columns:
        view[column] = view[column].fillna("").astype(str)
    st.markdown(
        '<div style="max-height:520px;overflow:auto;border:1px solid #ddd;border-radius:6px">'
        + view.to_html(index=False, escape=True)
        + "</div>",
        unsafe_allow_html=True,
    )


def preferred_columns(df: pd.DataFrame) -> list[str]:
    preferred = [
        "call_lane", "call_deadline", "lead_status", "lead_score", "opportunity_score_10", "confidence",
        "seller_name", "phone", "phone_1", "phone_2", "property_address", "seller_message", "call_summary",
        "timeline_bucket", "asking_price_extracted", "motivation", "missing_information",
        "recommended_next_question", "xleads_action", "rei_blackbook_tags", "risk_flags",
    ]
    return [column for column in preferred if column in df.columns]


st.title(APP_TITLE)
st.subheader(MODULE_TITLE)
st.write("XLeads handles texting, AI voice calls, and workflows. This app ranks opportunities, protects missed leads, and creates the team's call and follow-up queues.")

with st.sidebar:
    st.header("Lead Intelligence Settings")
    target_states_text = st.text_input("Target states", value=",".join(DEFAULT_TARGET_STATES))
    target_states = [item.strip().upper() for item in target_states_text.split(",") if item.strip()]
    st.caption("Raw leads outside these states are held for review. Seller replies are still analyzed so live opportunities are not discarded.")

uploaded_file = st.file_uploader("Upload XLeads CSV", type=["csv"])
if uploaded_file is None:
    st.warning("Upload an XLeads CSV to begin.")
    if st.button("Run built-in greatness test"):
        test_df = run_greatness_test()
        st.metric("Greatness tests passed", f"{int(test_df['passed'].sum())}/{len(test_df)}")
        show_table(test_df)
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
    with st.spinner("Scoring and sorting leads..."):
        scored = score_dataframe(normalized_df, file_mode, target_states=target_states)
        scored = ensure_unique_columns(scored)
        scored["inside_calling_hours"] = scored["seller_timezone"].apply(inside_calling_hours)
        scored["ai_call_allowed"] = scored["ai_call_allowed"].astype(bool) & scored["inside_calling_hours"]
        scored["human_call_task_allowed"] = scored["human_call_task_allowed"].astype(bool) & scored["inside_calling_hours"]
        st.session_state["scored_df"] = scored
        st.session_state["file_mode"] = file_mode

if "scored_df" not in st.session_state:
    st.stop()

scored_df = ensure_unique_columns(st.session_state["scored_df"])
file_mode = st.session_state["file_mode"]

if file_mode == "Seller Replies":
    metrics = [
        ("Total", len(scored_df)),
        ("Call Now", int((scored_df["call_lane"] == "Call Now").sum())),
        ("Call Today", int((scored_df["call_lane"] == "Call Today").sum())),
        ("Follow-Up", int(scored_df["call_lane"].isin(["Keep Qualifying", "Scheduled Follow-Up"]).sum())),
        ("Human Review", int((scored_df["call_lane"] == "Human Review").sum())),
        ("Blocked / Closed", int(scored_df["call_lane"].isin(["Do Not Contact", "Closed / No Call", "Duplicate / Suppress"]).sum())),
    ]
else:
    metrics = [
        ("Total Raw Leads", len(scored_df)),
        ("Priority Campaign", int((scored_df["lead_status"] == "Priority Campaign Lead").sum())),
        ("Ready for Campaign", int((scored_df["lead_status"] == "Ready for Campaign").sum())),
        ("Needs Skip Trace", int((scored_df["lead_status"] == "Needs Phone / Skip Trace").sum())),
        ("Review", int(scored_df["human_review_required"].astype(bool).sum())),
    ]

for column, (label, value) in zip(st.columns(len(metrics)), metrics):
    column.metric(label, value)

tabs = st.tabs(["Must Call Queue", "Missed Opportunities", "Follow-Up", "Compliance", "Skip Trace", "Campaign Queue", "All Leads", "Greatness Test"])

with tabs[0]:
    queue = scored_df[
        scored_df["must_call"].astype(bool)
        & scored_df["duplicate_primary"].astype(bool)
        & ~scored_df["opt_out_detected"].astype(bool)
        & ~scored_df["wrong_number_detected"].astype(bool)
    ].copy().sort_values(["call_priority_rank", "lead_score", "confidence"], ascending=[True, False, False])
    st.write("### Must Call Queue")
    show_table(queue, preferred_columns(queue))
    st.download_button("Download Must Call Queue", queue.to_csv(index=False).encode("utf-8"), "war_room_must_call_queue.csv", "text/csv")

with tabs[1]:
    watch = scored_df[
        scored_df["human_review_required"].astype(bool)
        | scored_df["other_property_opportunity"].astype(bool)
        | scored_df["price_expectation_review"].astype(bool)
        | scored_df["risk_flags"].astype(str).str.contains("OWNERSHIP_VERIFY|PROPERTY_SOLD|TEXT_ONLY", regex=True, na=False)
    ].copy()
    st.write("### Missed-Opportunity Watch")
    show_table(watch, preferred_columns(watch))

with tabs[2]:
    follow_up = scored_df[scored_df["call_lane"].isin(["Keep Qualifying", "Scheduled Follow-Up", "Human Review"])].copy()
    st.write("### Follow-Up and Next Questions")
    show_table(follow_up, preferred_columns(follow_up))
    st.download_button("Download Follow-Up Queue", follow_up.to_csv(index=False).encode("utf-8"), "war_room_follow_up_queue.csv", "text/csv")

with tabs[3]:
    compliance_columns = [column for column in ["seller_name", "phone", "property_address", "seller_message", "call_lane", "call_permission", "opt_out_detected", "wrong_number_detected", "duplicate_flag", "duplicate_primary", "risk_flags", "xleads_action"] if column in scored_df.columns]
    st.write("### Compliance and Call Permissions")
    show_table(scored_df, compliance_columns)

with tabs[4]:
    skiptrace = scored_df[(scored_df["xleads_action"].astype(str) == "SKIP_TRACE") & scored_df["duplicate_primary"].astype(bool)].copy()
    st.write("### Needs Skip Trace")
    st.caption("These records are kept out of texting and calling until a valid, compliant phone number is returned.")
    show_table(skiptrace, preferred_columns(skiptrace))
    st.download_button("Download Skip Trace Queue", skiptrace.to_csv(index=False).encode("utf-8"), "war_room_skiptrace_queue.csv", "text/csv")

with tabs[5]:
    campaign = scored_df[
        scored_df["lead_status"].isin(["Priority Campaign Lead", "Ready for Campaign"])
        & scored_df["duplicate_primary"].astype(bool)
    ].copy()
    st.write("### XLeads Campaign Queue")
    show_table(campaign, preferred_columns(campaign))
    st.download_button("Download XLeads Campaign Queue", campaign.to_csv(index=False).encode("utf-8"), "war_room_xleads_campaign_queue.csv", "text/csv")

with tabs[6]:
    st.write("### All Scored Leads")
    show_table(scored_df, limit=50)
    st.download_button("Download All Scored Leads", scored_df.to_csv(index=False).encode("utf-8"), "war_room_all_scored_leads.csv", "text/csv")

with tabs[7]:
    st.write("### Built-In Greatness Test")
    if st.button("Run Greatness Test", key="greatness_test_tab"):
        test_df = run_greatness_test()
        passed = int(test_df["passed"].sum())
        st.metric("Passed", f"{passed}/{len(test_df)}")
        show_table(test_df)
