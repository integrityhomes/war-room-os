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
st.title("XLeads Intake & CRM Sync")
st.caption(
    "Upload the XLeads ZIP or CSV, review the owner/property mapping, then optionally sync only safe records to Ninja CRM. "
    "This page never starts a texting, calling, or follow-up workflow."
)

with st.sidebar:
    st.header("Batch settings")
    default_tag = f"xleads-{datetime.now().strftime('%Y-%m-%d')}"
    campaign_tag = st.text_input("Campaign tag", value=default_tag)
    st.caption("Use a unique tag for each list so your team can find the batch later.")

uploaded = st.file_uploader("Upload XLeads export", type=["csv", "zip"])
if uploaded is None:
    st.info("Upload the XLeads Lead Trace ZIP or the extracted CSV to begin.")
    st.stop()

try:
    raw_df, source_filename = read_xleads_upload(uploaded.name, uploaded.getvalue())
    queue = prepare_sync_dataframe(raw_df, campaign_tag)
except Exception as exc:
    st.error(str(exc))
    st.stop()

st.success(f"Loaded {len(raw_df):,} rows from {source_filename}")
report = build_report(queue)
metric_items = [
    ("Total rows", report["total_rows"]),
    ("Ready to sync", report["ready_to_sync"]),
    ("DNC holds", report["dnc_holds"]),
    ("Multi-property review", report["multi_property_review"]),
    ("Duplicates suppressed", report["duplicates_suppressed"]),
    ("Missing phone/email", report["missing_contact_match"]),
    ("Missing property", report["missing_property"]),
]
for column, (label, value) in zip(st.columns(len(metric_items)), metric_items):
    column.metric(label, value)

st.warning(
    "Owners tied to more than one property are held for review so one property address cannot overwrite another on a single contact record."
)

preview_columns = [
    "seller_name", "phone", "phone_2", "email", "mailing_address", "property_address",
    "phone_type", "dnc_hold", "property_count_for_contact", "sync_action", "sync_reason", "crm_tags",
]
preview_columns = [column for column in preview_columns if column in queue.columns]

review_tab, safe_tab, hold_tab, sync_tab = st.tabs([
    "All records", "Ready to sync", "Held for review", "Ninja CRM sync"
])

with review_tab:
    st.dataframe(queue[preview_columns], use_container_width=True, hide_index=True)

with safe_tab:
    safe_queue = queue[queue["safe_to_sync"]].copy()
    st.dataframe(safe_queue[preview_columns], use_container_width=True, hide_index=True)

with hold_tab:
    held = queue[~queue["safe_to_sync"]].copy()
    st.dataframe(held[preview_columns], use_container_width=True, hide_index=True)

with sync_tab:
    st.subheader("Dry-run export")
    st.write(
        "Download this cleaned file for audit or manual CRM import. Mailing address and targeted property address remain separate."
    )
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
    st.caption(
        "Credentials stay in Streamlit Secrets. The sync only upserts contacts and custom fields; it does not add anyone to a workflow."
    )

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
        st.info(
            "Direct sync is not configured yet. Add HIGHLEVEL_TOKEN, HIGHLEVEL_LOCATION_ID, and the four property custom-field IDs/keys to Streamlit Secrets. "
            "The dry-run files above work now without credentials."
        )
    else:
        confirmation = st.checkbox(
            f"I reviewed the dry run and approve updating {report['ready_to_sync']:,} safe records."
        )
        if st.button("Sync safe records to Ninja CRM", type="primary", disabled=not confirmation):
            if report["ready_to_sync"] == 0:
                st.warning("There are no safe records to sync.")
            else:
                with st.spinner("Updating Ninja CRM contacts..."):
                    results = sync_safe_rows(queue, HighLevelClient(config))
                st.session_state["xleads_sync_results"] = results

        if "xleads_sync_results" in st.session_state:
            results: pd.DataFrame = st.session_state["xleads_sync_results"]
            success_count = int((results["sync_result"] == "SUCCESS").sum()) if not results.empty else 0
            failure_count = int((results["sync_result"] == "FAILED").sum()) if not results.empty else 0
            left, right = st.columns(2)
            left.metric("Successful updates", success_count)
            right.metric("Failed updates", failure_count)
            st.dataframe(results, use_container_width=True, hide_index=True)
            st.download_button(
                "Download sync audit report",
                results.to_csv(index=False).encode("utf-8"),
                file_name=f"{campaign_tag}-sync-audit.csv",
                mime="text/csv",
            )
