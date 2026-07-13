from __future__ import annotations

import hashlib
import io
import re

import pandas as pd
import requests
import streamlit as st

from lead_intelligence import DEFAULT_TARGET_STATES, score_dataframe

st.set_page_config(page_title="Return Results & Rerank", page_icon="🔁", layout="wide")

SHEET_ID = "1c3F6mwJwN-EnCKeTxw16f2EfcEAxh4H6WDQPDVkyPrc"
SHEET_GID = "0"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={SHEET_GID}"
TRUTHY = {"1", "true", "yes", "y", "dnc", "blocked", "stop"}


def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def lead_key_from_values(name: str, property_address: str, mailing_address: str) -> str:
    raw = "|".join([clean_text(name), clean_text(property_address), clean_text(mailing_address)]).lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_phone(value) -> str:
    digits = re.sub(r"\D", "", clean_text(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def truthy(value) -> bool:
    return clean_text(value).lower() in TRUTHY


def first_nonblank(row: pd.Series, names: list[str]) -> str:
    for name in names:
        value = clean_text(row.get(name, ""))
        if value:
            return value
    return ""


def ensure_key(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    if "lead_key" not in output.columns:
        output["lead_key"] = output.apply(
            lambda row: lead_key_from_values(
                row.get("seller_name", ""),
                row.get("property_address", ""),
                row.get("mailing_address", ""),
            ),
            axis=1,
        )
    return output


def read_results() -> pd.DataFrame:
    response = requests.get(SHEET_CSV_URL, timeout=30)
    response.raise_for_status()
    if "text/html" in str(response.headers.get("content-type", "")).lower():
        raise ValueError(
            "Google returned a sign-in page. Set the sheet to Anyone with the link — Viewer."
        )
    return pd.read_csv(io.BytesIO(response.content))


def merge_results(scored: pd.DataFrame, results: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    scored = ensure_key(scored)
    results = ensure_key(results).drop_duplicates("lead_key", keep="last").set_index("lead_key")
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
        dnc = truthy(first_nonblank(returned, ["dnc_flag", "DNC", "dnc", "do_not_call"]))
        no_phone = truthy(first_nonblank(returned, ["no_phone_found", "No Phone Found"]))

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
            merged.at[index, "notes"] = (
                clean_text(row.get("notes", "")) + " | Skiptrace returned DNC"
            ).strip(" |")

    return merged, matched


st.title("War Room OS")
st.subheader("Return Skip-Trace Results and Rerank")
st.success("War Room Skip Trace Queue is permanently connected.")
st.caption(f"Connected sheet ID: {SHEET_ID} | tab gid: {SHEET_GID}")

if "scored_df" not in st.session_state:
    st.warning("Run Intelligent Lead Ranking on the main page first.")
    st.stop()

if st.button("Pull Completed Results and Rerank", type="primary"):
    with st.spinner("Reading the return sheet, merging results, and reranking leads..."):
        try:
            results_df = read_results()
        except Exception as exc:
            st.error(f"Could not read the skip-trace return sheet: {exc}")
            st.stop()

        current = st.session_state["scored_df"].copy()
        merged, matched = merge_results(current, results_df)
        reranked = score_dataframe(
            merged,
            "Raw XLeads Property List",
            target_states=DEFAULT_TARGET_STATES,
        )
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

    if matched:
        st.success("Returned contact data was merged and the lead list was reranked.")
    else:
        st.warning("No returned rows matched. Confirm Zapier writes the lead_key field back to the sheet.")

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
