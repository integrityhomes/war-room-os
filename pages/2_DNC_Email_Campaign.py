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

with st.expander("TEAM INSTRUCTIONS — START HERE", expanded=True):
    st.markdown(
        """
### Part 1 — Get the completed XLeads LeadTrace file

1. Start on the **XLeads Skip Trace** page in the left menu.
2. Upload the brand-new property list.
3. Download **XLeads Paid LeadTrace Upload**.
4. In XLeads, import that file into **Property Leads / My Leads**.
5. In XLeads, export the list and select all six boxes:
   - **Overview**
   - **Lead Trace — Owner Contact Info**
   - **Property Details**
   - **Valuations**
   - **Loans**
   - **Liens**
6. Download the completed XLeads CSV or ZIP. Keep the original file unchanged.

### Part 2 — Build the cannot-call email lists

7. Return to this **DNC Email Campaign** page.
8. Give the batch a clear campaign tag in the left sidebar. Example: `danville-dnc-email-2026-08`.
9. Upload the original completed XLeads LeadTrace **CSV or ZIP**.
   - Do **not** upload the Email Ready file.
   - Do **not** upload the raw property list.
10. Confirm the green message **Paid LeadTrace Verified**.
11. Read the batch-specific explanation shown under the three totals before downloading anything.

### Part 3 — Choose the correct download

12. Use **DNC Email Campaign** when the assignment is: *email only the people whose phones are on confirmed DNC hold*.
13. Click **Download DNC Email Campaign CSV**.
14. Use **Cannot-Call Email** only when the assignment is broader and includes:
   - DNC phone holds
   - Phone-screening review
   - No valid approved phone
15. Never upload the **Email Suppression Audit** into an email campaign. It is for review only.
16. Never load both the DNC Email Campaign file and the Cannot-Call Email file into the same campaign. The DNC rows are already included in the broader Cannot-Call file.

### Part 4 — Import into the email campaign

17. Upload the downloaded campaign CSV into the approved email platform.
18. Map these fields when available:
   - `FirstName` → First Name
   - `LastName` → Last Name
   - `Email` → Email
   - `PropertyAddress` → Property Address
   - `PropertyCity` → Property City
   - `PropertyState` → Property State
   - `PropertyPostalCode` → Property ZIP
   - `RecipientAddress` → Owner Mailing Address
   - `CampaignTag` → Tag or List Name
19. Do not map or add a phone field. This email campaign file intentionally contains no phone-number columns.
20. Name the email list using the same campaign tag shown in the CSV.
21. Review a few records before launching to confirm the owner name, email, and property address match.

### Email campaign rules

- Do not email anyone in **Email Suppression Audit** without management review.
- Do not manually add an email that the bot removed.
- The email must use accurate sender and subject information.
- Include the company’s valid postal address and a clear unsubscribe method.
- Honor unsubscribe requests and maintain the suppression list.
- This page only prepares files. It does not automatically send emails or start a workflow.
        """
    )

with st.expander("WHAT EACH DOWNLOAD MEANS", expanded=True):
    st.markdown(
        """
- **DNC Email Campaign CSV:** the narrow file for people whose phones are specifically on DNC hold and whose emails are still usable.
- **All Cannot-Call Email Campaign CSV:** the broader file for every usable email where no phone is approved for calling.
- **Email Suppression Audit:** people the bot removed from email because an email opt-out, unsubscribe, complaint, suppression, or bounce may exist. Review only—do not campaign.

The download is flattened to **one row per email address**, so owners with multiple usable emails may appear on more than one row. Phone-number columns are intentionally removed.
        """
    )

with st.sidebar:
    st.header("Batch settings")
    campaign_tag = st.text_input("Campaign tag", value=f"dnc-email-{datetime.now().strftime('%Y-%m-%d')}")
    st.caption("Use a unique, easy-to-recognize tag for every batch.")

uploaded = st.file_uploader("Upload completed XLeads LeadTrace CSV or ZIP", type=["csv", "zip"])
if uploaded is None:
    st.info("Upload the original completed paid XLeads LeadTrace CSV or ZIP to begin.")
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
    st.warning(
        "Return to XLeads Skip Trace and complete paid LeadTrace. This page needs the returned XLeads CSV or ZIP with populated phone, DNC, and litigator screening results."
    )
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

other_cannot_call = max(len(cannot_call) - len(dnc_campaign), 0)

st.subheader("WHAT THESE NUMBERS MEAN FOR THIS BATCH — READ BEFORE DOWNLOADING")
st.markdown(
    f"""
### **{len(cannot_call):,} Cannot-Call Email rows**
This is the **broadest usable-email list**. It contains every usable, non-suppressed email where the bot did not find a phone approved for calling or texting.

It includes:
- The **{len(dnc_campaign):,} confirmed DNC email rows** shown below
- **{other_cannot_call:,} other cannot-call email rows** where the phone screening is unclear, no valid phone was found, or no phone was approved

**Use this file only when the assignment is to email everyone we cannot call.**

### **{len(dnc_campaign):,} DNC Email Campaign rows**
This is the **narrower confirmed-DNC subset**. These records have a phone that is specifically on DNC hold, plus a usable email that does not show a known email suppression flag.

**Use this file when the assignment is to email only people whose phones are confirmed DNC.**

These {len(dnc_campaign):,} rows are already included inside the {len(cannot_call):,}-row Cannot-Call file. **Do not upload both files into the same campaign**, or the same email address may receive duplicate messages.

### **{other_cannot_call:,} Other Cannot-Call Email rows**
These are the rows in the broad Cannot-Call file that are **not confirmed DNC**. They may have:
- Blank or unclear phone screening
- No valid phone number
- No phone approved for calling or texting

They are included in the broad Cannot-Call download but excluded from the confirmed-DNC download.

### **{len(suppressed):,} Email Suppression Review rows**
These records are **not campaign-ready**. The bot found a possible email opt-out, unsubscribe, complaint, suppression, bounce, or another warning.

**Never import this file into an email campaign. It is for management review only.**

### Important counting rule
These totals count **email rows**, not necessarily unique owners. One owner with two usable email addresses can appear on two rows.
    """
)

st.success(
    f"DOWNLOAD THE DNC EMAIL CAMPAIGN FILE ({len(dnc_campaign):,} rows) when the job is confirmed phone-DNC records only."
)
st.info(
    f"DOWNLOAD THE CANNOT-CALL EMAIL FILE ({len(cannot_call):,} rows) only when the job is everyone we cannot call."
)
st.error(
    f"NEVER CAMPAIGN THE EMAIL SUPPRESSION AUDIT ({len(suppressed):,} rows). REVIEW ONLY."
)

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
        "Use this file when the assignment is to email only the people whose phones are on DNC hold. "
        "It is one row per usable email and contains no phone-number columns."
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
    st.subheader("Do not email without management review")
    st.error("Never import this audit file into an email campaign.")
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
