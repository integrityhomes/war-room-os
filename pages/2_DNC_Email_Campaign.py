from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from xleads_campaign_control import analyze_returned_export, read_xleads_upload
from xleads_email_campaign import (
    cannot_call_email_export,
    dnc_email_campaign_export,
    email_suppression_audit,
)
from xleads_paid_verification import verify_paid_leadtrace


st.set_page_config(page_title="DNC Email Campaign", page_icon="✉️", layout="wide")
st.title("DNC Email Campaign Builder")
st.caption(
    "Create an email-campaign CSV only for owners whose phones are not approved for calling. "
    "No phone numbers are included in the campaign download."
)

with st.expander("How this page works", expanded=True):
    st.markdown(
        """
1. Upload the completed paid XLeads LeadTrace CSV or ZIP.
2. **Cannot-Call Email** includes valid emails where no phone is approved for text/voice.
3. **DNC Email Campaign** is narrower: it includes only records whose phone status is **DNC_PHONE_HOLD**.
4. Email opt-outs, unsubscribes, suppression flags, complaints, and bounce flags are excluded.
5. The download is flattened to one row per email and contains no phone-number columns.
        """
    )

with st.sidebar:
    st.header("Batch settings")
    campaign_tag = st.text_input("Campaign tag", value=f"dnc-email-{datetime.now().strftime('%Y-%m-%d')}")

uploaded = st.file_uploader("Upload completed XLeads LeadTrace CSV or ZIP", type=["csv", "zip"])
if uploaded is None:
    st.info("Upload the completed paid XLeads LeadTrace export to begin.")
    st.stop()

try:
    raw_df, source_filename = read_xleads_upload(uploaded.name, uploaded.getvalue())
except Exception as exc:
    st.error(str(exc))
    st.stop()

verification = verify_paid_leadtrace(raw_df)
if not verification.verified:
    st.error("Paid LeadTrace Not Verified")
    st.write(verification.reason)
    st.stop()

try:
    queue = analyze_returned_export(raw_df, campaign_tag)
    cannot_call = cannot_call_email_export(queue)
    dnc_campaign = dnc_email_campaign_export(queue)
    suppressed = email_suppression_audit(queue)
except Exception as exc:
    st.error(f"Could not build the email campaign files: {exc}")
    st.stop()

st.success(f"Paid LeadTrace Verified — loaded {len(raw_df):,} records from {source_filename}")
metrics = st.columns(3)
metrics[0].metric("Cannot-call email rows", len(cannot_call))
metrics[1].metric("DNC email campaign rows", len(dnc_campaign))
metrics[2].metric("Email suppression review", len(suppressed))

st.warning(
    "A phone DNC result does not automatically mean an email address is suppressed. "
    "This page still removes known email opt-outs, unsubscribes, complaints, suppressions, and bounces."
)

cannot_tab, dnc_tab, suppressed_tab = st.tabs([
    "Cannot-Call Email",
    "DNC Email Campaign",
    "Email Suppression Audit",
])

with cannot_tab:
    st.subheader("All usable emails for people we cannot call")
    st.caption("Includes DNC phone holds, phone-screening review, and records with no valid approved phone.")
    st.dataframe(cannot_call, use_container_width=True, hide_index=True)
    st.download_button(
        "Download All Cannot-Call Email Campaign CSV",
        cannot_call.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-all-cannot-call-email-campaign.csv",
        mime="text/csv",
        type="primary",
    )

with dnc_tab:
    st.subheader("DNC phone list — email campaign ready")
    st.caption(
        "This is the direct campaign file for records with DNC_PHONE_HOLD and a usable, non-suppressed email. "
        "It is one row per email and contains no phone-number columns."
    )
    st.dataframe(dnc_campaign, use_container_width=True, hide_index=True)
    st.download_button(
        "Download DNC Email Campaign CSV",
        dnc_campaign.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-dnc-email-campaign-ready.csv",
        mime="text/csv",
        type="primary",
    )

with suppressed_tab:
    st.subheader("Do not email without review")
    st.dataframe(suppressed, use_container_width=True, hide_index=True)
    st.download_button(
        "Download Email Suppression Audit",
        suppressed.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-email-suppression-audit.csv",
        mime="text/csv",
    )

st.divider()
st.caption(
    "Before launching a commercial email campaign, use accurate sender/subject information, include your valid postal address, "
    "provide a clear unsubscribe method, and honor opt-outs promptly."
)
