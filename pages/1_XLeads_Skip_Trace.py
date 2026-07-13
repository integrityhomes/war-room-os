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

st.set_page_config(page_title="XLeads Skip Trace", page_icon="📥", layout="wide")


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


def download_csv(label: str, frame: pd.DataFrame, filename: str, primary: bool = False) -> None:
    st.download_button(
        label,
        frame.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        type="primary" if primary else "secondary",
    )


st.title("War Room XLeads Skip Trace")
st.caption(
    "Use this page for the complete skip-trace workflow: prepare a new property list, run paid XLeads LeadTrace, "
    "verify the returned results, and create separate phone and email campaign files."
)

with st.expander("TEAM INSTRUCTIONS — START HERE", expanded=True):
    st.markdown(
        """
### New list workflow

1. **Upload the brand-new property CSV on this page.**
2. War Room will show **Paid LeadTrace Not Verified** and create a cleaned file.
3. Click **Download XLeads Paid LeadTrace Upload**.
4. In XLeads, upload that file into **Property Leads / My Leads**.
5. In XLeads, open **Export Leads** and check all six boxes below:
   - **Overview**
   - **Lead Trace — Owner Contact Info**
   - **Property Details**
   - **Valuations**
   - **Loans**
   - **Liens**
6. Click **Export Leads** to run the paid LeadTrace export.
7. Download the completed XLeads CSV or ZIP from XLeads.
8. Return to this page and upload the completed result.
9. Confirm the green message **Paid LeadTrace Verified**.
10. Download **Phone Ready** for the XLeads text/AI-voice workflow.
11. Download **Email Ready** for the XLeads email workflow.

### Important rules

- Phone numbers or emails merely visible in **My Leads** are **not proof** that paid LeadTrace ran.
- War Room only verifies paid LeadTrace when matching phone, DNC, and Litigator results are populated.
- Keep **Phone Ready** and **Email Ready** as separate imports.
- A phone on DNC hold may still have a usable email.
- Do not put **Email Only**, **Phone DNC Hold**, or **Screening Review** into the text/voice workflow.
        """
    )

with st.expander("WHAT EACH RESULT MEANS", expanded=False):
    st.markdown(
        """
- **Campaign Ready:** at least one usable channel—phone, email, or both.
- **Phone Ready:** at least one phone returned with DNC=False and Litigator=False.
- **Email Ready:** valid email with no detected unsubscribe, opt-out, suppression, complaint, or bounce flag.
- **Email Only:** usable email, but no phone approved for text/voice.
- **Phone DNC Hold:** all usable phones are DNC, litigator, or internal opt-out blocked.
- **Screening Review:** phone exists, but DNC or litigator results are blank or unclear.
- **No Usable Contact:** no usable phone or email was found.
        """
    )

with st.sidebar:
    st.header("Batch settings")
    default_tag = f"xleads-{datetime.now().strftime('%Y-%m-%d')}"
    campaign_tag = st.text_input("Campaign tag", value=default_tag)
    st.caption("Use a unique tag for each list so the team can find the batch later.")

uploaded = st.file_uploader(
    "Upload a raw property CSV or returned paid XLeads LeadTrace CSV/ZIP",
    type=["csv", "zip"],
)
if uploaded is None:
    st.info("Start with Step 1 above: upload the brand-new property list here.")
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
        "XLeads may already display phone numbers or emails before paid LeadTrace runs. "
        "War Room will not treat those fields as paid skip-trace results."
    )

    prepared = prepare_skiptrace_upload(raw_df)
    st.subheader("Your next action: run paid XLeads LeadTrace")
    st.write(
        "Download the cleaned file below, upload it into XLeads, select Overview, Lead Trace, Property Details, "
        "Valuations, Loans, and Liens, then upload the completed XLeads CSV or ZIP back to this same page."
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
    download_csv(
        "Download XLeads Paid LeadTrace Upload",
        prepared,
        f"{campaign_tag}-xleads-paid-leadtrace-upload.csv",
        primary=True,
    )
    st.stop()

st.success(
    f"Paid LeadTrace Verified — {verification.screened_rows:,} rows contain populated phone, DNC, and litigator screening results."
)
st.subheader("Your next action: review and download the XLeads campaign files")

try:
    queue = analyze_returned_export(raw_df, campaign_tag)
    report = build_report(queue)
except Exception as exc:
    st.error(f"Could not process the returned XLeads file: {exc}")
    st.stop()

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
    "Phone and email are separate lanes. A DNC or litigator result blocks the phone from text/voice, "
    "but a valid email can remain in the email queue unless an email suppression flag is present."
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
    st.caption("This is the full combined audit queue. Use the separate Phone Ready and Email Ready downloads for workflows.")
    show_html(campaign, preview)
    download_csv(
        "Download Combined Campaign Audit",
        campaign,
        f"{campaign_tag}-xleads-campaign-ready.csv",
    )

with tabs[1]:
    st.success("Import this file into the XLeads text and AI-voice workflow built by your team.")
    show_html(phone_ready, preview)
    download_csv(
        "Download XLeads Phone-Ready Queue",
        phone_ready,
        f"{campaign_tag}-xleads-phone-ready.csv",
        primary=True,
    )

with tabs[2]:
    st.success("Import this file into the XLeads email workflow built by your team.")
    show_html(email_ready, preview)
    download_csv(
        "Download XLeads Email-Ready Queue",
        email_ready,
        f"{campaign_tag}-xleads-email-ready.csv",
        primary=True,
    )

with tabs[3]:
    st.caption("These records have a usable email but no phone approved for text/voice.")
    show_html(email_only, preview)
    download_csv(
        "Download Email-Only Queue",
        email_only,
        f"{campaign_tag}-xleads-email-only.csv",
    )

with tabs[4]:
    st.error("Do not place these phone numbers into text or voice campaigns.")
    show_html(dnc_hold, preview)
    download_csv(
        "Download Phone DNC Hold Audit",
        dnc_hold,
        f"{campaign_tag}-phone-dnc-hold.csv",
    )

with tabs[5]:
    st.warning("These phones need another screening result before entering the text/voice workflow.")
    show_html(screening, preview)
    download_csv(
        "Download Screening Review Queue",
        screening,
        f"{campaign_tag}-phone-screening-review.csv",
    )

with tabs[6]:
    show_html(queue, preview)
    download_csv(
        "Download Full War Room Audit",
        queue,
        f"{campaign_tag}-war-room-full-audit.csv",
    )
    download_csv(
        "Download All Non-Campaign Review Records",
        review,
        f"{campaign_tag}-war-room-review.csv",
    )
