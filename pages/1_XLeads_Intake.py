from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from xleads_import_automation import (
    HighLevelClient,
    HighLevelConfig,
    build_report,
    crm_export,
    prepare_sync_dataframe,
    read_xleads_upload,
    sync_safe_rows,
)

st.set_page_config(page_title="XLeads Intake & CRM Sync", page_icon="📥", layout="wide")


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


st.title("XLeads Intake & CRM Sync")
st.caption(
    "Upload the XLeads ZIP or CSV, review owner/property mapping, then optionally sync only reviewed safe records to Ninja CRM. "
    "This page never starts texting, calling, or follow-up workflows."
)

with st.sidebar:
    st.header("Batch settings")
    default_tag = f"xleads-{datetime.now().strftime('%Y-%m-%d')}"
    campaign_tag = st.text_input("Campaign tag", value=default_tag)

uploaded = st.file_uploader("Upload XLeads export", type=["csv", "zip"])
if uploaded is None:
    st.info("Upload the XLeads Lead Trace ZIP or extracted CSV to begin.")
    st.stop()

try:
    raw_df, source_filename = read_xleads_upload(uploaded.name, uploaded.getvalue())
    queue = prepare_sync_dataframe(raw_df, campaign_tag)
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.success(f"Loaded {len(raw_df):,} rows from {source_filename}")
report = build_report(queue)
metrics = [
    ("Total", report["total_rows"]),
    ("Ready to sync", report["ready_to_sync"]),
    ("DNC hold", report["dnc_holds"]),
    ("Screening review", report["screening_review"]),
    ("Multi-property", report["multi_property_review"]),
    ("Duplicates", report["duplicates_suppressed"]),
]
for column, (label, value) in zip(st.columns(len(metrics)), metrics):
    column.metric(label, value)

st.warning(
    "DNC=True or Litigator=True is held. Blank/unknown screening goes to Screening Review. "
    "A later phone can be used when an earlier phone is blocked and the later phone is explicitly clear."
)

preview = [
    "seller_name", "phone", "phone_2", "email", "mailing_address", "property_address",
    "phone_type", "sync_action", "sync_reason", "property_count_for_contact", "crm_tags",
]
all_tab, ready_tab, dnc_tab, review_tab, other_tab, sync_tab = st.tabs(
    ["All", "Ready", "DNC Hold", "Screening Review", "Other Holds", "Ninja CRM Sync"]
)

with all_tab:
    show_html(queue, preview)

with ready_tab:
    ready = queue[queue["sync_action"].eq("READY_TO_SYNC")].copy()
    show_html(ready, preview)

with dnc_tab:
    dnc_hold = queue[queue["sync_action"].eq("DNC_HOLD")].copy()
    show_html(dnc_hold, preview)

with review_tab:
    screening = queue[queue["sync_action"].eq("SCREENING_REVIEW")].copy()
    show_html(screening, preview)

with other_tab:
    other = queue[~queue["sync_action"].isin(["READY_TO_SYNC", "DNC_HOLD", "SCREENING_REVIEW"])].copy()
    show_html(other, preview)

with sync_tab:
    export_df = crm_export(queue)
    st.download_button(
        "Download cleaned CRM queue",
        export_df.to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-crm-queue.csv",
        mime="text/csv",
    )
    st.download_button(
        "Download held-record review queue",
        queue[~queue["safe_to_sync"]].to_csv(index=False).encode("utf-8"),
        file_name=f"{campaign_tag}-held-review.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("Optional direct Ninja CRM sync")
    secrets = st.secrets
    config = HighLevelConfig(
        token=str(secrets.get("HIGHLEVEL_TOKEN", "")),
        location_id=str(secrets.get("HIGHLEVEL_LOCATION_ID", "")),
        property_address_field=str(secrets.get("HIGHLEVEL_PROPERTY_ADDRESS_FIELD", "")),
        property_city_field=str(secrets.get("HIGHLEVEL_PROPERTY_CITY_FIELD", "")),
        property_state_field=str(secrets.get("HIGHLEVEL_PROPERTY_STATE_FIELD", "")),
        property_zip_field=str(secrets.get("HIGHLEVEL_PROPERTY_ZIP_FIELD", "")),
        api_base=str(secrets.get("HIGHLEVEL_API_BASE", "https://services.leadconnectorhq.com")),
    )

    if not config.configured:
        st.info("Direct sync is not configured. Dry-run downloads work without credentials.")
    else:
        confirmation = st.checkbox(
            f"I reviewed the dry run and approve updating {report['ready_to_sync']:,} READY_TO_SYNC records."
        )
        if st.button("Sync safe records to Ninja CRM", type="primary", disabled=not confirmation):
            with st.spinner("Updating Ninja CRM contacts..."):
                st.session_state["xleads_sync_results"] = sync_safe_rows(queue, HighLevelClient(config))

        if "xleads_sync_results" in st.session_state:
            results = st.session_state["xleads_sync_results"]
            success = int((results["sync_result"] == "SUCCESS").sum()) if not results.empty else 0
            failed = int((results["sync_result"] == "FAILED").sum()) if not results.empty else 0
            left, right = st.columns(2)
            left.metric("Successful", success)
            right.metric("Failed", failed)
            show_html(results, ["audit_id", "seller_name", "phone", "property_address", "sync_result", "contact_id", "error"])
            st.download_button(
                "Download sync audit report",
                results.to_csv(index=False).encode("utf-8"),
                file_name=f"{campaign_tag}-sync-audit.csv",
                mime="text/csv",
            )
