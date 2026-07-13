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

DNC_TRUE = {"1", "true", "yes", "y", "dnc", "blocked", "stop", "on dnc", "listed"}
DNC_FALSE = {"0", "false", "no", "n", "clear", "not dnc", "not on dnc", "approved", "ok"}


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


def first_nonblank(row: pd.Series, names: list[str]) -> str:
    for name in names:
        value = clean_text(row.get(name, ""))
        if value:
            return value
    return ""


def parse_dnc_status(row: pd.Series) -> str:
    raw = first_nonblank(
        row,
        [
            "dnc_flag",
            "DNC",
            "dnc",
            "do_not_call",
            "national_dnc",
            "federal_dnc",
            "dnc_status",
        ],
    ).lower()
    if raw in DNC_TRUE:
        return "BLOCKED_DNC"
    if raw in DNC_FALSE:
        return "DNC_CLEAR"
    return "DNC_UNKNOWN"


def truthy(value) -> bool:
    return clean_text(value).lower() in DNC_TRUE


def ensure_key(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    computed = output.apply(
        lambda row: lead_key_from_values(
            row.get("seller_name", ""),
            row.get("property_address", ""),
            row.get("mailing_address", ""),
        ),
        axis=1,
    )
    if "lead_key" not in output.columns:
        output["lead_key"] = computed
    else:
        blank = output["lead_key"].fillna("").astype(str).str.strip().eq("")
        output.loc[blank, "lead_key"] = computed.loc[blank]
    return output


def read_results() -> pd.DataFrame:
    response = requests.get(SHEET_CSV_URL, timeout=30)
    response.raise_for_status()
    if "text/html" in str(response.headers.get("content-type", "")).lower():
        raise ValueError("Google returned a sign-in page. Set the sheet to Anyone with the link — Viewer.")
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

        raw_phones = [
            first_nonblank(returned, ["phone_1", "phone1", "Phone 1", "primary_phone", "phone"]),
            first_nonblank(returned, ["phone_2", "phone2", "Phone 2"]),
            first_nonblank(returned, ["phone_3", "phone3", "Phone 3"]),
        ]
        phones = [normalize_phone(phone) for phone in raw_phones if normalize_phone(phone)]
        dnc_status = parse_dnc_status(returned)
        no_phone = truthy(first_nonblank(returned, ["no_phone_found", "No Phone Found"]))
        source = first_nonblank(returned, ["skiptrace_source", "provider", "source"])
        confidence = first_nonblank(returned, ["phone_confidence", "confidence", "Phone Confidence"])
        line_type = first_nonblank(returned, ["phone_type", "line_type", "Phone Type"])

        merged.at[index, "skiptrace_source"] = source
        merged.at[index, "skiptrace_date"] = first_nonblank(returned, ["skiptrace_date", "completed_at"])
        merged.at[index, "skiptrace_dnc_status"] = dnc_status
        merged.at[index, "skiptrace_no_phone_found"] = no_phone
        merged.at[index, "skiptrace_phone_confidence"] = confidence
        merged.at[index, "skiptrace_phone_type"] = line_type
        merged.at[index, "skiptrace_phone_1_raw"] = phones[0] if phones else ""
        merged.at[index, "skiptrace_phone_2_raw"] = phones[1] if len(phones) > 1 else ""
        merged.at[index, "skiptrace_phone_3_raw"] = phones[2] if len(phones) > 2 else ""

        if no_phone:
            compliance_status = "NO_PHONE_FOUND"
        elif not phones:
            compliance_status = "INVALID_OR_MISSING_PHONE"
        elif dnc_status == "BLOCKED_DNC":
            compliance_status = "DNC_BLOCKED_NO_CALL"
        elif dnc_status == "DNC_UNKNOWN":
            compliance_status = "DNC_NOT_VERIFIED_NO_CALL"
        else:
            compliance_status = "APPROVED_FOR_CONTACT"

        merged.at[index, "skiptrace_compliance_status"] = compliance_status

        if compliance_status == "APPROVED_FOR_CONTACT":
            merged.at[index, "phone"] = phones[0]
            merged.at[index, "phone_1"] = phones[0]
            if len(phones) > 1:
                merged.at[index, "phone_2"] = phones[1]
            if len(phones) > 2:
                merged.at[index, "phone_3"] = phones[2]
        else:
            merged.at[index, "phone"] = ""
            merged.at[index, "phone_1"] = ""
            merged.at[index, "phone_2"] = ""
            merged.at[index, "phone_3"] = ""
            merged.at[index, "notes"] = (
                clean_text(row.get("notes", "")) + f" | Compliance hold: {compliance_status}"
            ).strip(" |")

        email = first_nonblank(returned, ["email_1", "email", "Email 1", "Email"])
        if email:
            merged.at[index, "email"] = email

    return merged, matched


def apply_hard_compliance_gate(scored: pd.DataFrame) -> pd.DataFrame:
    output = scored.copy()
    if "skiptrace_compliance_status" not in output.columns:
        output["skiptrace_compliance_status"] = ""

    hold_mask = output["skiptrace_compliance_status"].astype(str).isin(
        [
            "DNC_BLOCKED_NO_CALL",
            "DNC_NOT_VERIFIED_NO_CALL",
            "INVALID_OR_MISSING_PHONE",
            "NO_PHONE_FOUND",
        ]
    )

    for column in ["must_call", "ai_call_allowed", "human_call_task_allowed"]:
        if column in output.columns:
            output.loc[hold_mask, column] = False

    if "call_lane" in output.columns:
        output.loc[hold_mask, "call_lane"] = "Compliance Hold / No Call"
    if "call_permission" in output.columns:
        output.loc[hold_mask, "call_permission"] = "BLOCKED"
    if "xleads_action" in output.columns:
        output.loc[hold_mask, "xleads_action"] = "HOLD_COMPLIANCE"
    if "lead_status" in output.columns:
        output.loc[hold_mask, "lead_status"] = "Compliance Hold"
    if "risk_flags" in output.columns:
        output.loc[hold_mask, "risk_flags"] = output.loc[hold_mask, "risk_flags"].fillna("").astype(str).apply(
            lambda value: (value + " | DNC_OR_PHONE_COMPLIANCE_HOLD").strip(" |")
        )

    return output


st.title("War Room OS")
st.subheader("Return Skip-Trace Results and Rerank")
st.success("War Room Skip Trace Queue is permanently connected.")
st.caption(f"Connected sheet ID: {SHEET_ID} | tab gid: {SHEET_GID}")
st.warning(
    "Hard safety rule: a returned phone is never released to XLeads or Must Call unless DNC status is explicitly clear. Blank or unknown DNC status is treated as No Call."
)

if "scored_df" not in st.session_state:
    st.warning("Run Intelligent Lead Ranking on the main page first.")
    st.stop()

if st.button("Pull Completed Results and Rerank", type="primary"):
    with st.spinner("Reading the return sheet, validating DNC status, merging results, and reranking leads..."):
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
        reranked = apply_hard_compliance_gate(reranked)
        st.session_state["scored_df"] = reranked
        st.session_state["file_mode"] = "Raw XLeads Property List"

        approved_mask = reranked.get("skiptrace_compliance_status", pd.Series("", index=reranked.index)).astype(str).eq(
            "APPROVED_FOR_CONTACT"
        )
        ready = reranked[
            reranked["lead_status"].isin(["Priority Campaign Lead", "Ready for Campaign"])
            & reranked["duplicate_primary"].astype(bool)
            & approved_mask
        ].copy()
        needs_skip = reranked[reranked["lead_status"].eq("Needs Phone / Skip Trace")].copy()
        compliance_hold = reranked[
            reranked.get("skiptrace_compliance_status", pd.Series("", index=reranked.index)).astype(str).isin(
                [
                    "DNC_BLOCKED_NO_CALL",
                    "DNC_NOT_VERIFIED_NO_CALL",
                    "INVALID_OR_MISSING_PHONE",
                    "NO_PHONE_FOUND",
                ]
            )
        ].copy()
        must_call = reranked[
            reranked["must_call"].astype(bool)
            & reranked["duplicate_primary"].astype(bool)
            & ~reranked["opt_out_detected"].astype(bool)
            & ~reranked["wrong_number_detected"].astype(bool)
            & approved_mask
        ].copy()

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Matched return rows", matched)
    col2.metric("DNC-clear campaign", len(ready))
    col3.metric("Still needs skip trace", len(needs_skip))
    col4.metric("Compliance hold / no call", len(compliance_hold))
    col5.metric("DNC-clear must call", len(must_call))

    if matched:
        st.success("Returned data was matched by seller/address, checked through the hard DNC gate, and reranked.")
    else:
        st.warning(
            "No returned rows matched. The app matches by seller name, property address, and mailing address; no lead_key column is required."
        )

    st.download_button(
        "Download Final DNC-Clear XLeads Campaign Queue",
        ready.to_csv(index=False).encode("utf-8"),
        "war_room_final_dnc_clear_xleads_campaign_queue.csv",
        "text/csv",
    )
    st.download_button(
        "Download Final DNC-Clear Must Call Queue",
        must_call.to_csv(index=False).encode("utf-8"),
        "war_room_final_dnc_clear_must_call_queue.csv",
        "text/csv",
    )
    st.download_button(
        "Download Compliance Hold — Do Not Call",
        compliance_hold.to_csv(index=False).encode("utf-8"),
        "war_room_compliance_hold_do_not_call.csv",
        "text/csv",
    )
    st.download_button(
        "Download Remaining Skip Trace Queue",
        needs_skip.to_csv(index=False).encode("utf-8"),
        "war_room_remaining_skiptrace_queue.csv",
        "text/csv",
    )
