from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from xleads_campaign_control import (
    analyze_returned_export,
    build_report,
    campaign_export,
    email_export,
    phone_export,
    prepare_skiptrace_upload,
    read_xleads_upload,
    review_export,
)
from xleads_paid_verification import verify_paid_leadtrace

st.set_page_config(page_title="XLeads Skip Trace Control Center", page_icon="📥", layout="wide")


def show_html(df: pd.DataFrame, columns: list[str], limit: int = 100) -> None:
    if df.empty:
        st.caption("No records in this queue.")
        return
    view = df.loc[:, ~df.columns.duplicated(keep="first")].copy()
    view = view[[column for column in columns if column in view.columns]].head(limit).copy()
    for column in view.columns:
        view[column] = view[column].fillna("").astype(str)
    st.markdown(
        '<div style="max-height:520px;overflow:auto;border:1px solid #ddd;border-radius:6px">'
        + view.to_html(index=False, escape=True)
        + "</div>",
        unsafe_allow_html=True,
    )


st.title("War Room XLeads Skip Trace Control Center")
st.caption(
    "Prepare a property list for paid XLeads LeadTrace, then upload the returned XLeads CSV or ZIP. "
    "War Room only unlocks campaign queues after it verifies populated phone, DNC, and litigator results."
)

with st.sidebar:
    st.header("Batch settings")
    default_tag = f"xleads-{datetime.now().strftime('%Y-%m-%d')}"
    campaign_tag = st.text_input("Campaign tag", value=default_tag)

uploaded = st.file_uploader(
    "Upload a raw property CSV or returned paid XLeads LeadTrace CSV/ZIP",
    type=["csv", "zip"],
)
if uploaded is None:
    st.info(
        "Upload a raw property list to prepare it for paid LeadTrace, or upload the returned XLeads file to build campaign queues."
    )
    st.stop()

try:
    raw_df, source_filename = read_xleads_upload(uploaded.name, uploaded.getvalue())
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.success(f"Loaded {len(raw_df):,} rows from {source_filename}")
verification = verify_paid_leadtrace(raw_df)

if not verification.verified:
    st.error("Paid LeadTrace Not Verified — Skip Trace Still Required")
    st.write(verification.reason)

    left, right = st.columns(2)
    left.metric("Paired phone/DNC/litigator groups", verification.paired_phone_groups)
    right.metric("Rows with completed screening", verification.screened_rows)

    st.warning(
        "XLeads may show phone numbers or emails on My Leads before paid LeadTrace runs. "
        "War Room will not treat those contact fields as skip-traced results without populated matching DNC and litigator evidence."
    )

    prepared = prepare_skiptrace_upload(raw_df)
    st.subheader("Step 1 — Run Paid XLeads LeadTrace")
    st.write(
        "Download the cleaned property upload below, run paid LeadTrace in XLeads, then bring the returned CSV or ZIP back to this page."
    )
    st.metric("Properties prepared", len(prepared))
    preview_columns = [
        "seller_name",
        "property_address",
        "mailing_address",
        "owner_type",
        "avm",
        "wholesale_value",
        "mls_status",
    ]
    show_html(prepared, preview_columns)
    st.download_button(
        "Download XLeads Paid LeadTrace Upload",
        prepared.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-xleads-paid-leadtrace-upload.csv",
        mime="text/csv",
        type="primary",
    )
    st.stop()

st.success(
    f"Paid LeadTrace Verified — {verification.screened_rows:,} rows contain populated phone, DNC, and litigator screening results."
)

try:
    queue = analyze_returned_export(raw_df, campaign_tag)
    report = build_report(queue)
except Exception as exc:
    st.error(f"Could not process the returned XLeads file: {exc}")
    st.stop()

st.subheader("Step 2 — Verified Paid LeadTrace Results")
row1 = st.columns(4)
row1[0].metric("Total", report["total"])
row1[1].metric("Campaign ready", report["campaign_ready"])
row1[2].metric("Phone ready", report["phone_ready"])
row1[3].metric("Email ready", report["email_ready"])
row2 = st.columns(4)
row2[0].metric("Email only", report["email_only"])
row2[1].metric("Phone DNC hold", report["dnc_phone_hold"])
row2[2].metric("Screening review", report["screening_review"])
row2[3].metric("No usable contact", report["no_contact"])

st.info(
    "Phone and email are separate lanes. DNC=True or Litigator=True blocks that phone from the phone queue, "
    "but a valid email can still enter the email queue unless an email opt-out, unsubscribe, suppression, complaint, or bounce flag is present."
)
st.warning(
    "War Room prepares files only. It does not automatically launch XLeads texting, AI voice, calling, or email workflows. "
    "Review the queues before importing or starting campaigns."
)

campaign = campaign_export(queue)
phone_ready = phone_export(queue)
email_ready = email_export(queue)
email_only = queue[queue["email_only"]].copy()
dnc_hold = queue[queue["phone_action"].eq("DNC_PHONE_HOLD")].copy()
screening = queue[queue["phone_action"].eq("SCREENING_REVIEW")].copy()
review = review_export(queue)

preview = [
    "seller_name",
    "phone",
    "phone_2",
    "phone_3",
    "phone_type",
    "email",
    "email_2",
    "mailing_address",
    "property_address",
    "phone_action",
    "email_action",
    "campaign_action",
    "xleads_tags",
]

tabs = st.tabs(
    [
        "Campaign Ready",
        "Phone Ready",
        "Email Ready",
        "Email Only",
        "Phone DNC Hold",
        "Screening Review",
        "Full Audit",
    ]
)

with tabs[0]:
    show_html(campaign, preview)
    st.download_button(
        "Download XLeads Combined Campaign Queue",
        campaign.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-xleads-campaign-ready.csv",
        mime="text/csv",
        type="primary",
    )

with tabs[1]:
    show_html(phone_ready, preview)
    st.download_button(
        "Download XLeads Phone-Ready Queue",
        phone_ready.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-xleads-phone-ready.csv",
        mime="text/csv",
    )

with tabs[2]:
    show_html(email_ready, preview)
    st.download_button(
        "Download XLeads Email-Ready Queue",
        email_ready.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-xleads-email-ready.csv",
        mime="text/csv",
    )

with tabs[3]:
    st.caption(
        "These records do not have a phone ready for calling/texting, but they do have an email ready for the email lane."
    )
    show_html(email_only, preview)
    st.download_button(
        "Download Email-Only Queue",
        email_only.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-xleads-email-only.csv",
        mime="text/csv",
    )

with tabs[4]:
    show_html(dnc_hold, preview)
    st.download_button(
        "Download Phone DNC Hold Audit",
        dnc_hold.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-phone-dnc-hold.csv",
        mime="text/csv",
    )

with tabs[5]:
    show_html(screening, preview)
    st.download_button(
        "Download Screening Review Queue",
        screening.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-phone-screening-review.csv",
        mime="text/csv",
    )

with tabs[6]:
    show_html(queue, preview)
    st.download_button(
        "Download Full War Room Audit",
        queue.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-war-room-full-audit.csv",
        mime="text/csv",
    )
    st.download_button(
        "Download All Non-Campaign Review Records",
        review.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-war-room-review.csv",
        mime="text/csv",
    )
