from __future__ import annotations

import re

import pandas as pd
import streamlit as st

st.set_page_config(page_title="XLeads DNC Safety Gate", page_icon="🛡️", layout="wide")

CLEAR = {"clear", "cleared", "no", "false", "0", "not listed", "not on dnc", "approved", "ok", "pass", "passed"}
BLOCKED = {"yes", "true", "1", "listed", "on dnc", "blocked", "dnc", "stop", "do not call"}


def clean_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def find_column(df: pd.DataFrame, names: list[str]) -> str | None:
    lookup = {str(column).strip().lower(): column for column in df.columns}
    for name in names:
        match = lookup.get(name.lower())
        if match is not None:
            return match
    return None


def series_from(df: pd.DataFrame, names: list[str], default: str = "") -> pd.Series:
    column = find_column(df, names)
    if column is None:
        return pd.Series([default] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str)


def normalize_phone(value) -> str:
    digits = re.sub(r"\D", "", clean_text(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def parse_status(value) -> str:
    text = clean_text(value).lower()
    if text in CLEAR:
        return "CLEAR"
    if text in BLOCKED:
        return "BLOCKED"
    return "UNKNOWN"


def show_table(df: pd.DataFrame, columns: list[str] | None = None, limit: int = 100) -> None:
    if df.empty:
        st.caption("No records in this queue.")
        return
    view = df.copy()
    if columns:
        view = view[[column for column in columns if column in view.columns]].copy()
    if len(view) > limit:
        st.caption(f"Showing first {limit} of {len(view)} records.")
        view = view.head(limit).copy()
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

    output["seller_name"] = series_from(output, ["seller_name", "Seller Name", "owner_name", "Owner Name", "name"])
    output["property_address"] = series_from(output, ["property_address", "Property Address", "address", "PropertyAddress"])
    output["mailing_address"] = series_from(output, ["mailing_address", "Mailing Address", "owner_address", "Owner Address"])

    phone_candidates = [
        series_from(output, ["phone_1", "Phone 1", "phone1", "primary_phone", "phone"]),
        series_from(output, ["phone_2", "Phone 2", "phone2"]),
        series_from(output, ["phone_3", "Phone 3", "phone3"]),
    ]
    output["xleads_phone_1"] = phone_candidates[0].map(normalize_phone)
    output["xleads_phone_2"] = phone_candidates[1].map(normalize_phone)
    output["xleads_phone_3"] = phone_candidates[2].map(normalize_phone)

    output["national_dnc_status"] = series_from(
        output,
        ["national_dnc_status", "National DNC", "federal_dnc", "Federal DNC", "national_dnc", "dnc_national"],
    ).map(parse_status)
    output["state_dnc_status"] = series_from(
        output,
        ["state_dnc_status", "State DNC", "state_dnc", "dnc_state"],
    ).map(parse_status)
    output["company_dnc_status"] = series_from(
        output,
        ["company_dnc_status", "Company DNC", "internal_dnc", "entity_dnc", "company_specific_dnc"],
    ).map(parse_status)

    output["prior_opt_out"] = series_from(
        output,
        ["prior_opt_out", "opt_out", "opt_out_detected", "Do Not Contact", "do_not_contact"],
    ).map(lambda value: parse_status(value) == "BLOCKED")
    output["wrong_number"] = series_from(
        output,
        ["wrong_number", "wrong_number_detected", "Wrong Number"],
    ).map(lambda value: parse_status(value) == "BLOCKED")

    output["valid_phone"] = output[["xleads_phone_1", "xleads_phone_2", "xleads_phone_3"]].apply(
        lambda row: next((phone for phone in row if clean_text(phone)), ""),
        axis=1,
    )

    all_dnc_clear = (
        output["national_dnc_status"].eq("CLEAR")
        & output["state_dnc_status"].eq("CLEAR")
        & output["company_dnc_status"].eq("CLEAR")
    )
    approved = (
        output["valid_phone"].ne("")
        & all_dnc_clear
        & ~output["prior_opt_out"]
        & ~output["wrong_number"]
    )

    output["compliance_status"] = "COMPLIANCE_HOLD_DO_NOT_CALL_OR_TEXT"
    output.loc[approved, "compliance_status"] = "APPROVED_FOR_CONTACT_REVIEW"

    output["compliance_reason"] = output.apply(
        lambda row: "APPROVED" if row["compliance_status"] == "APPROVED_FOR_CONTACT_REVIEW" else " | ".join(
            reason
            for reason, condition in [
                ("NO_VALID_10_DIGIT_PHONE", not bool(clean_text(row["valid_phone"]))),
                ("NATIONAL_DNC_NOT_CLEAR", row["national_dnc_status"] != "CLEAR"),
                ("STATE_DNC_NOT_CLEAR", row["state_dnc_status"] != "CLEAR"),
                ("COMPANY_DNC_NOT_CLEAR", row["company_dnc_status"] != "CLEAR"),
                ("PRIOR_OPT_OUT", bool(row["prior_opt_out"])),
                ("WRONG_NUMBER", bool(row["wrong_number"])),
            ]
            if condition
        ),
        axis=1,
    )

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
    "Fail-closed rule: a phone is blocked unless National DNC, State DNC, and Company DNC are all explicitly CLEAR. Blank or unknown means Do Not Call or Text."
)

source_df: pd.DataFrame | None = None
if "scored_df" in st.session_state:
    source_df = st.session_state["scored_df"].copy()
    st.success("Using the current War Room scored lead list.")
else:
    uploaded = st.file_uploader("Upload XLeads skip-trace result CSV", type=["csv"])
    if uploaded is not None:
        source_df = pd.read_csv(uploaded)

if source_df is None:
    st.warning("Run Intelligent Lead Ranking first, or upload the XLeads skip-trace result CSV.")
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

    display = [
        "seller_name",
        "property_address",
        "valid_phone",
        "national_dnc_status",
        "state_dnc_status",
        "company_dnc_status",
        "prior_opt_out",
        "wrong_number",
        "compliance_status",
        "compliance_reason",
    ]

    st.write("### DNC-Clear — Human Review Required")
    show_table(approved, display)
    st.download_button(
        "Download DNC-Clear XLeads Campaign Queue",
        approved.to_csv(index=False).encode("utf-8"),
        "war_room_xleads_dnc_clear_campaign_queue.csv",
        "text/csv",
    )

    st.write("### Compliance Hold — Do Not Call or Text")
    show_table(hold, display)
    st.download_button(
        "Download Compliance Hold List",
        hold.to_csv(index=False).encode("utf-8"),
        "war_room_compliance_hold_do_not_call_or_text.csv",
        "text/csv",
    )
