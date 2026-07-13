from __future__ import annotations

import re

import pandas as pd
import streamlit as st

st.set_page_config(page_title="XLeads DNC Safety Gate", page_icon="🛡️", layout="wide")

CLEAR = {"clear", "cleared", "no", "false", "0", "not listed", "not on dnc", "approved", "ok", "pass", "passed"}
BLOCK = {"yes", "true", "1", "listed", "on dnc", "blocked", "dnc", "stop", "do not call", "do not text"}


def clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(value).lower()).strip("_")


def phone(value) -> str:
    digits = re.sub(r"\D", "", clean(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def dnc(value) -> str:
    text = clean(value).lower()
    if text in CLEAR:
        return "CLEAR"
    if text in BLOCK or "do not call" in text or "do not text" in text:
        return "BLOCKED"
    return "UNKNOWN"


def columns_with(df: pd.DataFrame, include: list[str], exclude: list[str] | None = None) -> list[str]:
    exclude = exclude or []
    return [
        column
        for column in df.columns
        if any(token in norm(column) for token in include)
        and not any(token in norm(column) for token in exclude)
    ]


def first_matching_column(df: pd.DataFrame, names: list[str]) -> str | None:
    lookup = {norm(column): column for column in df.columns}
    for name in names:
        if norm(name) in lookup:
            return lookup[norm(name)]
    return None


def text_series(df: pd.DataFrame, names: list[str]) -> pd.Series:
    column = first_matching_column(df, names)
    if column is None:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str)


def first_phone(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    if not columns:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    candidates = pd.DataFrame(index=df.index)
    for position, column in enumerate(columns):
        candidates[f"p{position}"] = df[column].fillna("").astype(str).map(phone)
    return candidates.apply(lambda row: next((value for value in row if value), ""), axis=1)


def combined_dnc(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    if not columns:
        return pd.Series(["UNKNOWN"] * len(df), index=df.index, dtype="object")
    values = df[columns].fillna("").astype(str)

    def combine(row: pd.Series) -> str:
        statuses = [dnc(value) for value in row]
        if "BLOCKED" in statuses:
            return "BLOCKED"
        if statuses and all(value == "CLEAR" for value in statuses):
            return "CLEAR"
        return "UNKNOWN"

    return values.apply(combine, axis=1)


def schema_report(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in df.columns:
        name = norm(column)
        if not any(token in name for token in ["phone", "mobile", "cell", "tel", "dnc", "do_not_call", "opt_out"]):
            continue
        values = [clean(value) for value in df[column].tolist() if clean(value)]
        rows.append(
            {
                "column": str(column),
                "nonblank_rows": len(values),
                "sample_values": " | ".join(list(dict.fromkeys(values))[:3]),
            }
        )
    return pd.DataFrame(rows)


def show_html(df: pd.DataFrame, columns: list[str], limit: int = 100) -> None:
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


def apply_gate(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    output = df.copy()

    output["seller_name"] = text_series(output, ["seller_name", "seller name", "owner_name", "owner name", "name"])
    output["property_address"] = text_series(output, ["property_address", "property address", "address"])
    output["mailing_address"] = text_series(output, ["mailing_address", "mailing address", "owner_address", "owner address"])

    phone_columns = columns_with(
        output,
        ["phone", "mobile", "cell", "telephone", "tel_"],
        ["dnc", "status", "type", "score", "confidence", "carrier", "valid", "verified", "date", "count"],
    )
    output["valid_phone"] = first_phone(output, phone_columns)

    all_dnc_columns = columns_with(output, ["dnc", "do_not_call", "donotcall"])
    national_columns = [column for column in all_dnc_columns if any(token in norm(column) for token in ["national", "federal"])]
    state_columns = [column for column in all_dnc_columns if "state" in norm(column)]
    company_columns = [
        column for column in all_dnc_columns
        if any(token in norm(column) for token in ["company", "internal", "entity", "specific"])
    ]

    output["national_dnc_status"] = combined_dnc(output, national_columns)
    output["state_dnc_status"] = combined_dnc(output, state_columns)
    output["company_dnc_status"] = combined_dnc(output, company_columns)
    output["xleads_dnc_status"] = combined_dnc(output, all_dnc_columns)

    opt_out_columns = columns_with(output, ["opt_out", "do_not_contact", "wrong_number"])
    output["prior_opt_out"] = False
    output["wrong_number"] = False
    for column in opt_out_columns:
        name = norm(column)
        blocked = output[column].fillna("").astype(str).map(lambda value: dnc(value) == "BLOCKED")
        if "wrong_number" in name:
            output["wrong_number"] = output["wrong_number"] | blocked
        else:
            output["prior_opt_out"] = output["prior_opt_out"] | blocked

    approved = (
        output["valid_phone"].ne("")
        & output["national_dnc_status"].eq("CLEAR")
        & output["state_dnc_status"].eq("CLEAR")
        & output["company_dnc_status"].eq("CLEAR")
        & ~output["prior_opt_out"]
        & ~output["wrong_number"]
    )

    output["compliance_status"] = "COMPLIANCE_HOLD_DO_NOT_CALL_OR_TEXT"
    output.loc[approved, "compliance_status"] = "APPROVED_FOR_CONTACT_REVIEW"

    def reason(row: pd.Series) -> str:
        if row["compliance_status"] == "APPROVED_FOR_CONTACT_REVIEW":
            return "APPROVED"
        reasons = []
        if not row["valid_phone"]:
            reasons.append("NO_VALID_10_DIGIT_PHONE")
        if row["national_dnc_status"] != "CLEAR":
            reasons.append("NATIONAL_DNC_NOT_CLEAR")
        if row["state_dnc_status"] != "CLEAR":
            reasons.append("STATE_DNC_NOT_CLEAR")
        if row["company_dnc_status"] != "CLEAR":
            reasons.append("COMPANY_DNC_NOT_CLEAR")
        if row["xleads_dnc_status"] == "BLOCKED":
            reasons.append("XLEADS_DNC_BLOCKED")
        if row["prior_opt_out"]:
            reasons.append("PRIOR_OPT_OUT")
        if row["wrong_number"]:
            reasons.append("WRONG_NUMBER")
        return " | ".join(reasons)

    output["compliance_reason"] = output.apply(reason, axis=1)
    output["phone"] = ""
    output.loc[approved, "phone"] = output.loc[approved, "valid_phone"]
    output["xleads_action"] = "HOLD_COMPLIANCE"
    output.loc[approved, "xleads_action"] = "READY_FOR_XLEADS_CAMPAIGN"
    output["call_lane"] = "Compliance Hold / No Call"
    output.loc[approved, "call_lane"] = "Eligible After Human Review"
    for column in ["must_call", "ai_call_allowed", "human_call_task_allowed"]:
        if column not in output.columns:
            output[column] = False
        output.loc[~approved, column] = False

    return output, {
        "phone_columns": phone_columns,
        "national_dnc_columns": national_columns,
        "state_dnc_columns": state_columns,
        "company_dnc_columns": company_columns,
        "all_dnc_columns": all_dnc_columns,
    }


st.title("War Room OS")
st.subheader("XLeads Federal + State + Company DNC Safety Gate")
st.error(
    "Fail-closed rule: a phone is blocked unless National DNC, State DNC, "
    "and Company DNC are all explicitly CLEAR. Blank or unknown means Do Not Call or Text."
)

uploaded = st.file_uploader(
    "Upload the XLeads skip-trace/export CSV directly",
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

report = schema_report(source_df)
with st.expander("Inspect detected XLeads phone and DNC columns", expanded=True):
    if report.empty:
        st.warning("No phone or DNC-style column names were detected in this CSV.")
    else:
        st.dataframe(report, hide_index=True, use_container_width=True)
    st.download_button(
        "Download XLeads Column Report",
        report.to_csv(index=False).encode("utf-8"),
        "xleads_column_report.csv",
        "text/csv",
    )

if st.button("Apply Hard DNC Safety Gate", type="primary"):
    gated, detected = apply_gate(source_df)
    st.session_state["scored_df"] = gated

    approved = gated[gated["compliance_status"].eq("APPROVED_FOR_CONTACT_REVIEW")].copy()
    hold = gated[~gated["compliance_status"].eq("APPROVED_FOR_CONTACT_REVIEW")].copy()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total checked", len(gated))
    col2.metric("DNC-clear for review", len(approved))
    col3.metric("Compliance hold", len(hold))

    st.write("### Detected XLeads fields")
    st.json(detected)

    if not detected["phone_columns"]:
        st.warning("No recognizable phone columns were found in this export.")
    if not detected["national_dnc_columns"] or not detected["state_dnc_columns"] or not detected["company_dnc_columns"]:
        st.warning(
            "This export does not contain explicit National, State, and Company DNC-clear fields. "
            "All affected records remain blocked."
        )

    display = [
        "seller_name", "property_address", "valid_phone",
        "national_dnc_status", "state_dnc_status", "company_dnc_status",
        "xleads_dnc_status", "prior_opt_out", "wrong_number",
        "compliance_status", "compliance_reason",
    ]

    st.write("### DNC-Clear - Human Review Required")
    show_html(approved, display)
    st.download_button(
        "Download DNC-Clear XLeads Campaign Queue",
        approved.to_csv(index=False).encode("utf-8"),
        "war_room_xleads_dnc_clear_campaign_queue.csv",
        "text/csv",
    )

    st.write("### Compliance Hold - Do Not Call or Text")
    show_html(hold, display)
    st.download_button(
        "Download Compliance Hold List",
        hold.to_csv(index=False).encode("utf-8"),
        "war_room_compliance_hold_do_not_call_or_text.csv",
        "text/csv",
    )
