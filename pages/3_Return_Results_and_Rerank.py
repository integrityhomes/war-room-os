from __future__ import annotations

import hashlib
import io
import re
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests
import streamlit as st

from lead_intelligence import DEFAULT_TARGET_STATES, score_dataframe

st.set_page_config(page_title="Return Results & Rerank", page_icon="🔁", layout="wide")

TRUTHY = {"1", "true", "yes", "y", "dnc", "blocked", "stop"}


def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def get_secret(name: str, default: str = "") -> str:
    try:
        return clean_text(st.secrets.get(name, default))
    except Exception:
        return default


def lead_key_from_values(name: str, property_address: str, mailing_address: str) -> str:
    raw = "|".join([clean_text(name), clean_text(property_address), clean_text(mailing_address)]).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_phone(value) -> str:
    digits = re.sub(r"\D", "", clean_text(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def is_truthy(value) -> bool:
    return clean_text(value).lower() in TRUTHY


def google_sheet_to_csv_url(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    if "export?format=csv" in value or "output=csv" in value:
        return value

    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    if not match:
        return value

    sheet_id = match.group(1)
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    gid = query.get("gid", [""])[0]
    if not gid and parsed.fragment:
        fragment = parse_qs(parsed.fragment)
        gid = fragment.get("gid", [""])[0]
    gid = gid or "0"
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def configured_sheet_value() -> str:
    direct = get_secret("SKIPTRACE_RESULTS_CSV_URL")
    if direct:
        return direct

    normal_link = get_secret("SKIPTRACE_RESULTS_SHEET_URL")
    if normal_link:
        return normal_link

    sheet_id = get_secret("SKIPTRACE_RESULTS_SHEET_ID")
    gid = get_secret("SKIPTRACE_RESULTS_GID", "0")
    if sheet_id:
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit?gid={gid}#gid={gid}"
    return ""


def read_results(url: str) -> pd.DataFrame:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content_type = clean_text(response.headers.get("content-type", "")).lower()
    if "text/html" in content_type:
        raise ValueError(
            "Google returned a sign-in or permission page instead of CSV. Share the sheet as Anyone with the link — Viewer, or add Google service-account access."
        )
    return pd.read_csv(io.BytesIO(response.content))


def ensure_key(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    if "lead_key" not in output.columns:
        output["lead_key"] = output.apply(
            lambda row: lead_key_from_values(
                row.get("seller_name", ""), row.get("property_address", ""), row.get("mailing_address", "")
            ),
            axis=1,
        )
    return output


def first_nonblank(row: pd.Series, names: list[str]) -> str:
    for name in names:
        value = clean_text(row.get(name, ""))
        if value:
            return value
    return ""


def merge_results(scored: pd.DataFrame, results: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    scored = ensure_key(scored)
    results = ensure_key(results)
    results = results.drop_duplicates("lead_key", keep="last").set_index("lead_key")
    merged = scored.copy()
    matched = 0

    for index, row in merged.iterrows():
        key = row["lead_key"]
        if key not in results.index:
            continue
        returned = results.loc[key]
        if isinstance(returned, pd.DataFrame):
            returned = returned.iloc[-1]
        matched += 1

        phones = [
            first_nonblank(returned, ["phone_1", "phone1", "Phone 1", "primary_phone", "phone"]),
            first_nonblank(returned, ["phone_2", "phone2", "Phone 2"]),
            first_nonblank(returned, ["phone_3", "phone3", "Phone 3"]),
        ]
        phones = [normalize_phone(phone) for phone in phones if normalize_phone(phone)]
        dnc = is_truthy(first_nonblank(returned, ["dnc_flag", "DNC", "dnc", "do_not_call"]))
        no_phone = is_truthy(first_nonblank(returned, ["no_phone_found", "No Phone Found"]))

        if phones and not dnc:
            merged.at[index, "phone"] = phones[0]
            merged.at[index, "phone_1"] = phones[0]
            if len(phones) > 1:
                merged.at[index, "phone_2"] = phones[1]
            if len(phones) > 2:
                merged.at[index, "phone_3"] = phones[2]

        email = first_nonblank(returned, ["email_1", "email", "Email 1", "Email"])
        if email:
            merged.at[index, "email"] = email

        merged.at[index, "skiptrace_source"] = first_nonblank(returned, ["skiptrace_source", "source"])
        merged.at[index, "skiptrace_date"] = first_nonblank(returned, ["skiptrace_date", "completed_at"])
        merged.at[index, "skiptrace_dnc_flag"] = dnc
        merged.at[index, "skiptrace_no_phone_found"] = no_phone
        if dnc:
            merged.at[index, "phone"] = ""
            merged.at[index, "notes"] = (clean_text(row.get("notes", "")) + " | Skiptrace returned DNC").strip(" |")

    return merged, matched


st.title("War Room OS")
st.subheader("Return Skip-Trace Results and Rerank")
st.write(
    "This page reads completed skip-trace results from the War Room Skip Trace Queue Google Sheet, "
    "merges returned phones and emails into the current lead list, reruns the intelligence engine, and rebuilds the final queues."
)

if "scored_df" not in st.session_state:
    st.warning("Run Intelligent Lead Ranking on the main page first.")
    st.stop()

saved_value = configured_sheet_value()
current_value = st.session_state.get("skiptrace_results_sheet_url", saved_value)
sheet_value = st.text_input(
    "War Room Skip Trace Queue Google Sheet link",
    value=current_value,
    placeholder="Paste the normal Google Sheets edit link here",
)
if sheet_value:
    st.session_state["skiptrace_results_sheet_url"] = sheet_value

csv_url = google_sheet_to_csv_url(sheet_value)
if not csv_url:
    st.error(
        "Paste the War Room Skip Trace Queue Google Sheet link above. For a permanent connection, save it in Streamlit secrets as SKIPTRACE_RESULTS_SHEET_URL."
    )
    st.stop()

if saved_value:
    st.success("Permanent skip-trace return sheet connection is configured.")
else:
    st.info(
        "This sheet is connected for the current app session. Save the same link as SKIPTRACE_RESULTS_SHEET_URL in Streamlit secrets to make it permanent across restarts."
    )

if st.button("Pull Completed Results and Rerank", type="primary"):
    with st.spinner("Reading the return sheet, merging results, and reranking leads..."):
        try:
            results_df = read_results(csv_url)
        except Exception as exc:
            st.error(f"Could not read the skip-trace return sheet: {exc}")
            st.stop()

        current = st.session_state["scored_df"].copy()
        merged, matched = merge_results(current, results_df)
        reranked = score_dataframe(merged, "Raw XLeads Property List", target_states=DEFAULT_TARGET_STATES)
        st.session_state["scored_df"] = reranked
        st.session_state["file_mode"] = "Raw XLeads Property List"

        ready = reranked[
            reranked["lead_status"].isin(["Priority Campaign Lead", "Ready for Campaign"])
            & reranked["duplicate_primary"].astype(bool)
        ].copy()
        needs_skip = reranked[reranked["lead_status"].eq("Needs Phone / Skip Trace")].copy()
        must_call = reranked[
            reranked["must_call"].astype(bool)
            & reranked["duplicate_primary"].astype(bool)
            & ~reranked["opt_out_detected"].astype(bool)
            & ~reranked["wrong_number_detected"].astype(bool)
        ].copy()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Matched return rows", matched)
    col2.metric("Ready for campaign", len(ready))
    col3.metric("Still needs skip trace", len(needs_skip))
    col4.metric("Must call", len(must_call))

    if matched == 0:
        st.warning("No returned rows matched the current lead list. Confirm that Zapier writes the lead_key field back to the sheet.")
    else:
        st.success("Returned contact data was merged and the full lead list was reranked.")

    st.download_button(
        "Download Final XLeads Campaign Queue",
        ready.to_csv(index=False).encode("utf-8"),
        "war_room_final_xleads_campaign_queue.csv",
        "text/csv",
    )
    st.download_button(
        "Download Final Must Call Queue",
        must_call.to_csv(index=False).encode("utf-8"),
        "war_room_final_must_call_queue.csv",
        "text/csv",
    )
    st.download_button(
        "Download Remaining Skip Trace Queue",
        needs_skip.to_csv(index=False).encode("utf-8"),
        "war_room_remaining_skiptrace_queue.csv",
        "text/csv",
    )
