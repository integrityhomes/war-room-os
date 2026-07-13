from __future__ import annotations

import re

import pandas as pd
import streamlit as st

st.set_page_config(page_title="XLeads DNC Safety Gate", page_icon="🛡️", layout="wide")

CLEAR_VALUES = {
    "clear", "cleared", "no", "false", "0", "not listed",
    "not on dnc", "approved", "ok", "pass", "passed",
}
BLOCK_VALUES = {
    "yes", "true", "1", "listed", "on dnc", "blocked",
    "dnc", "stop", "do not call", "do not text",
}


def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean_text(value).lower()).strip("_")


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lookup = {normalized_name(column): column for column in df.columns}
    for candidate in candidates:
        match = lookup.get(normalized_name(candidate))
        if match is not None:
            return match
    return None


def series_from(df: pd.DataFrame, candidates: list[str], default: str = "") -> pd.Series:
    column = find_column(df, candidates)
    if column is None:
        return pd.Series([default] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str)


def normalize_phone(value) -> str:
    digits = re.sub(r"\D", "", clean_text(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def parse_dnc(value) -> str:
    text = clean_text(value).lower()
    if text in CLEAR_VALUES:
        return "CLEAR"
    if text in BLOCK_VALUES or "do not call" in text or text == "dnc":
        return "BLOCKED"
    return "UNKNOWN"


def parse_block_flag(value) -> bool:
    text = clean_text(value).lower()
    return text in BLOCK_VALUES or "do not call" in text or "do not text" in text


def show_table(df: pd.DataFrame, columns: list[str], limit: int = 100) -> None:
    if df.empty:
        st.caption("No records in this queue.")
        return
    view = df[[column for column in columns if column in df.columns]].head(limit).copy()
    for column in view.columns:
        view[column] = view[column].fillna("").astype(str)
    st.markdown(
        '<div style="max-height:520px;overflow:auto;border:1px solid #ddd;border-radius:6px">'
        + view.to_html(index=False, escape=True)
        + "</div>",
        unsafe_allow_html=True,
    )


def apply_gate(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()

    output["seller_name"] = series_from(
        output, ["seller_name", "seller name", "owner_name", "owner name", "name"]
    )
    output["property_address"] = series_from(
        output, ["property_address", "property address", "address", "propertyaddress"]
    )
    output["mailing_address"] = series_from(
        output, ["mailing_address", "mailing address", "owner_address", "owner address"]
    )

    phone_series = [
        series_from(
            output,
            [
                "phone_1", "phone 1", "phone1", "primary_phone", "primary phone",
                "owner phone 1", "owner_phone_1", "mobile phone", "phone",
            ],
        ),
        series_from(
            output,
            ["phone_2", "phone 2", "phone2", "owner phone 2", "owner_phone_2"],
        ),
        series_from(
            output,
            ["phone_3", "phone 3", "phone3", "owner phone 3", "owner_phone_3"],
        ),
    ]

    output["xleads_phone_1"] = phone_series[0].map(normalize_phone)
    output["xleads_phone_2"] = phone_series[1].map(normalize_phone)
    output["xleads_phone_3"] = phone_series[2].map(normalize_phone)
    output["valid_phone"] = output[
        ["xleads_phone_1", "xleads_phone_2", "xleads_phone_3"]
    ].apply(lambda row: next((phone for phone in row if phone), ""), axis=1)

    output["national_dnc_status"] = series_from(
        output,
        [
            "national_dnc_status", "national dnc status", "national dnc",
            "federal_dnc", "federal dnc", "dnc_national",
        ],
    ).map(parse_dnc)
    output["state_dnc_status"] = series_from(
        output,
        ["state_dnc_status", "state dnc status", "state dnc", "dnc_state"],
    ).map(parse_dnc)
    output["company_dnc_status"] = series_from(
        output,
        [
            "company_dnc_status", "company dnc status", "company dnc",
            "internal_dnc", "internal dnc", "company_specific_dnc",
        ],
    ).map(parse_dnc)

    output["prior_opt_out"] = series_from(
        output,
        [
            "prior_opt_out", "prior opt out", "opt_out", "opt out",
            "opt_out_detected", "do_not_contact", "do not contact",
        ],
    ).map(parse_block_flag)
    output["wrong_number"] = series_from(
        output,
        ["wrong_number", "wrong number", "wrong_number_detected"],
    ).map(parse_block_flag)

    all_clear = (
        output["national_dnc_status"].eq("CLEAR")
        & output["state_dnc_status"].eq("CLEAR")
        & output["company_dnc_status"].eq("CLEAR")
    )
    approved = (
        output["valid_phone"].ne("")
        & all_clear
        & ~output["prior_opt_out"]
        & ~output["wrong_number"]
    )

    output["compliance_status"] = "COMPLIANCE_HOLD_DO_NOT_CALL_OR_TEXT"
    output.loc[approved, "compliance_status"] = "APPROVED_FOR_CONTACT_REVIEW"

    def reason_for(row: pd.Series) -> str:
        if row["compliance_status"] == "APPROVED_FOR_CONTACT_REVIEW":
            return "APPROVED"
        reasons: list[str] = []
        if not clean_text(row["valid_phone"]):
            reasons.append("NO_VALID_10_DIGIT_PHONE")
        if row["national_dnc_status"] != "CLEAR":
            reasons.append("NATIONAL_DNC_NOT_CLEAR")
        if row["state_dnc_status"] != "CLEAR":
            reasons.append("STATE_DNC_NOT_CLEAR")
        if row["company_dnc_status"] != "CLEAR":
            reasons.append("COMPANY_DNC_NOT_CLEAR")
        if bool(row["prior_opt_out"]):
            reasons.append("PRIOR_OPT_OUT")
        if bool(row["wrong_number"]):
            reasons.append("WRONG_NUMBER")
        return " | ".join(reasons)

    output["compliance_reason"] = output.apply(reason_for, axis=1)

    for column in ["must_call", "ai_call_allowed", "human_call_task_allowed"]:
        if column not in output.columns:
            output[column] = False
        output.loc[~approved, column] = False

    output["phone"] = ""
    output.loc[approved, "phone"] = output.loc[approved, "valid_phone"]
    output["xleads_action"] = "HOLD_COMPLIANCE"
    output.loc[approved, "xleads_action"] = "READY_FOR_XLEADS_CAMPAIGN"
    output["call_lane"] = "Compliance Hold / No Call"
    output.loc[approved, "call_lane"] = "Eligible After Human Review"

    return output


st.title("War Room OS")
st.subheader("XLeads Federal + State + Company DNC Safety Gate")
st.error(
    "Fail-closed rule: a phone is blocked unless National DNC, State DNC, "
    "and Company DNC are all explicitly CLEAR. Blank or unknown means Do Not Call or Text."
)

uploaded = st.file_uploader(
    "Optional: upload the XLeads skip-trace/export CSV directly",
    type=["csv"],
    key="xleads_dnc_upload",
)

source_df: pd.DataFrame | None = None
if uploaded is not None:
    source_df = pd.read_csv(uploaded)
    st.success(f"Using uploaded XLeads file: {uploaded.name}")
elif "scored_df" in st.session_state:
    source_df = st.session_state["scored_df"].copy()
    st.success("Using the current War Room scored lead list.")

if source_df is None:
    st.warning("Upload the XLeads CSV here, or run Intelligent Lead Ranking first.")
    st.stop()

if st.button("Apply Hard DNC Safety Gate", type="primary"):
    gated = apply_gate(source_df)
    st.session_state["scored_df"] = gated

    approved = gated[gated["compliance_status"].eq("APPROVED_FOR_CONTACT_REVIEW")].copy()
    hold = gated[~gated["compliance_status"].eq("APPROVED_FOR_CONTACT_REVIEW")].copy()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total checked", len(gated))
    col2.metric("DNC-clear for review", len(approved))
    col3.metric("Compliance hold", len(hold))

    display_columns = [
        "seller_name", "property_address", "valid_phone",
        "national_dnc_status", "state_dnc_status", "company_dnc_status",
        "prior_opt_out", "wrong_number", "compliance_status", "compliance_reason",
    ]

    st.write("### DNC-Clear - Human Review Required")
    show_table(approved, display_columns)
    st.download_button(
        "Download DNC-Clear XLeads Campaign Queue",
        approved.to_csv(index=False).encode("utf-8"),
        "war_room_xleads_dnc_clear_campaign_queue.csv",
        "text/csv",
    )

    st.write("### Compliance Hold - Do Not Call or Text")
    show_table(hold, display_columns)
    st.download_button(
        "Download Compliance Hold List",
        hold.to_csv(index=False).encode("utf-8"),
        "war_room_compliance_hold_do_not_call_or_text.csv",
        "text/csv",
    )
