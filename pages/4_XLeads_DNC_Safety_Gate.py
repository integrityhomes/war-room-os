from __future__ import annotations

import re

import pandas as pd
import streamlit as st

st.set_page_config(page_title="XLeads DNC Safety Gate", page_icon="🛡️", layout="wide")

CLEAR = {"clear", "cleared", "no", "false", "0", "not listed", "not on dnc", "approved", "ok", "pass", "passed"}
BLOCK = {"yes", "true", "1", "listed", "on dnc", "blocked", "dnc", "stop", "do not call", "do not text"}
OUTPUT_COLUMNS = {
    "seller_name", "property_address", "first_found_phone", "xleads_screened_phone",
    "xleads_screened_phone_type", "xleads_screen_status", "national_dnc_status",
    "state_dnc_status", "company_dnc_status", "prior_opt_out", "wrong_number",
    "compliance_status", "phone", "xleads_action", "call_lane", "must_call",
    "ai_call_allowed", "human_call_task_allowed", "compliance_reason",
}


def clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", clean(value).lower()).strip("_")


def unique_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[:, ~df.columns.duplicated(keep="first")].copy()


def normalize_phone(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = str(int(value)) if isinstance(value, float) and value.is_integer() else clean(value)
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]

    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def parse_flag(value) -> str:
    text = clean(value).lower()
    if text in CLEAR:
        return "CLEAR"
    if text in BLOCK or "do not call" in text or "do not text" in text:
        return "BLOCKED"
    return "UNKNOWN"


def find_column(df: pd.DataFrame, names: list[str]) -> str | None:
    lookup = {norm(column): str(column) for column in df.columns}
    for name in names:
        if norm(name) in lookup:
            return lookup[norm(name)]
    return None


def get_text(df: pd.DataFrame, names: list[str]) -> pd.Series:
    column = find_column(df, names)
    if column is None:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str)


def detect_phone_groups(df: pd.DataFrame) -> list[dict[str, str]]:
    lookup = {norm(column): str(column) for column in df.columns}
    groups = []
    for column in df.columns:
        key = norm(column)
        if re.fullmatch(r"contact\d+phone_\d+", key):
            groups.append(
                {
                    "phone": str(column),
                    "type": lookup.get(f"{key}_type", ""),
                    "dnc": lookup.get(f"{key}_dnc", ""),
                    "litigator": lookup.get(f"{key}_litigator", ""),
                }
            )
    return groups


def inspect_columns(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for position, column in enumerate(df.columns):
        key = norm(column)
        if not any(token in key for token in ["phone", "dnc", "litigator", "opt_out", "wrong_number"]):
            continue
        series = df.iloc[:, position]
        values = [clean(value) for value in series.tolist() if clean(value)]
        rows.append(
            {
                "column": str(column),
                "nonblank_rows": len(values),
                "sample_values": " | ".join(list(dict.fromkeys(values))[:3]),
            }
        )
    return pd.DataFrame(rows)


def evaluate_contact(row: pd.Series, groups: list[dict[str, str]]) -> pd.Series:
    first_found = ""
    first_clear = ""
    first_type = ""
    saw_dnc = saw_litigator = saw_unknown = False

    for group in groups:
        candidate = normalize_phone(row.get(group["phone"], ""))
        if not candidate:
            continue
        if not first_found:
            first_found = candidate

        dnc_status = parse_flag(row.get(group["dnc"], "")) if group["dnc"] else "UNKNOWN"
        litigator_status = parse_flag(row.get(group["litigator"], "")) if group["litigator"] else "UNKNOWN"

        saw_dnc = saw_dnc or dnc_status == "BLOCKED"
        saw_litigator = saw_litigator or litigator_status == "BLOCKED"
        saw_unknown = saw_unknown or dnc_status == "UNKNOWN" or litigator_status == "UNKNOWN"

        if dnc_status == "CLEAR" and litigator_status == "CLEAR" and not first_clear:
            first_clear = candidate
            first_type = clean(row.get(group["type"], "")) if group["type"] else ""

    if first_clear:
        status = "XLEADS_DNC_AND_LITIGATOR_CLEAR"
    elif not first_found:
        status = "NO_VALID_PHONE"
    elif saw_dnc:
        status = "XLEADS_DNC_BLOCKED"
    elif saw_litigator:
        status = "XLEADS_LITIGATOR_BLOCKED"
    elif saw_unknown:
        status = "XLEADS_SCREEN_UNKNOWN"
    else:
        status = "NO_CLEAR_PHONE"

    return pd.Series(
        {
            "first_found_phone": first_found,
            "xleads_screened_phone": first_clear,
            "xleads_screened_phone_type": first_type,
            "xleads_screen_status": status,
        }
    )


def apply_gate(source: pd.DataFrame) -> pd.DataFrame:
    df = unique_columns(source)
    df = df.drop(columns=[column for column in OUTPUT_COLUMNS if column in df.columns], errors="ignore")

    df["seller_name"] = get_text(df, ["seller_name", "seller name", "owner_name", "owner name", "name"])
    df["property_address"] = get_text(df, ["property_address", "property address", "address"])

    groups = detect_phone_groups(df)
    df = pd.concat([df, df.apply(lambda row: evaluate_contact(row, groups), axis=1)], axis=1)

    df["national_dnc_status"] = "UNKNOWN"
    df["state_dnc_status"] = "UNKNOWN"
    df["company_dnc_status"] = "UNKNOWN"
    df["prior_opt_out"] = False
    df["wrong_number"] = False

    for column in list(df.columns):
        key = norm(column)
        values = df[column].fillna("").astype(str)
        if "opt_out" in key or "do_not_contact" in key:
            df["prior_opt_out"] = df["prior_opt_out"] | values.map(lambda value: parse_flag(value) == "BLOCKED")
        if "wrong_number" in key:
            df["wrong_number"] = df["wrong_number"] | values.map(lambda value: parse_flag(value) == "BLOCKED")

    clear = df["xleads_screen_status"].eq("XLEADS_DNC_AND_LITIGATOR_CLEAR")
    df["compliance_status"] = "COMPLIANCE_HOLD_DO_NOT_CALL_OR_TEXT"
    df.loc[clear, "compliance_status"] = "XLEADS_CLEAR_PENDING_DNC_SCOPE_CONFIRMATION"
    df["phone"] = ""
    df["xleads_action"] = "HOLD_COMPLIANCE"
    df["call_lane"] = "Compliance Hold / No Call"
    df["must_call"] = False
    df["ai_call_allowed"] = False
    df["human_call_task_allowed"] = False

    def reason(row: pd.Series) -> str:
        reasons = []
        if row["xleads_screen_status"] != "XLEADS_DNC_AND_LITIGATOR_CLEAR":
            reasons.append(row["xleads_screen_status"])
        reasons.extend(
            ["NATIONAL_DNC_NOT_CONFIRMED", "STATE_DNC_NOT_CONFIRMED", "COMPANY_DNC_NOT_CONFIRMED"]
        )
        if bool(row["prior_opt_out"]):
            reasons.append("PRIOR_OPT_OUT")
        if bool(row["wrong_number"]):
            reasons.append("WRONG_NUMBER")
        return " | ".join(reasons)

    df["compliance_reason"] = df.apply(reason, axis=1)
    return unique_columns(df)


def show_html(df: pd.DataFrame, columns: list[str], limit: int = 100) -> None:
    if df.empty:
        st.caption("No records in this queue.")
        return
    view = unique_columns(df)
    view = view[[column for column in columns if column in view.columns]].head(limit).copy()
    for column in view.columns:
        view[column] = view[column].fillna("").astype(str)
    st.markdown(
        '<div style="max-height:520px;overflow:auto;border:1px solid #ddd;border-radius:6px">'
        + view.to_html(index=False, escape=True)
        + "</div>",
        unsafe_allow_html=True,
    )


st.title("War Room OS")
st.subheader("XLeads Phone-by-Phone DNC + Litigator Safety Gate")
st.error(
    "DNC=True, Litigator=True, blank screening, or unknown screening is blocked. "
    "DNC=False and Litigator=False only passes XLeads screening. "
    "Contact remains blocked until federal, state, and company DNC scope is confirmed."
)

uploaded = st.file_uploader("Upload the XLeads export CSV", type=["csv"], key="xleads_dnc_upload")
if uploaded is None:
    st.warning("Upload the XLeads CSV on this page to run the safety gate.")
    st.stop()

try:
    source_df = unique_columns(pd.read_csv(uploaded))
    report = inspect_columns(source_df)
except Exception as exc:
    st.error(f"Could not read or inspect the XLeads CSV: {exc}")
    st.stop()

with st.expander("Inspect detected XLeads phone, DNC, and litigator columns", expanded=True):
    show_html(report, ["column", "nonblank_rows", "sample_values"], limit=200)
    st.download_button(
        "Download XLeads Column Report",
        report.to_csv(index=False).encode("utf-8"),
        "xleads_column_report.csv",
        "text/csv",
    )

if st.button("Apply Hard DNC Safety Gate", type="primary"):
    try:
        gated = apply_gate(source_df)
    except Exception as exc:
        st.error(f"Could not apply the DNC safety gate: {exc}")
        st.stop()

    st.session_state["scored_df"] = gated
    pending = gated[gated["compliance_status"].eq("XLEADS_CLEAR_PENDING_DNC_SCOPE_CONFIRMATION")].copy()
    hold = gated[gated["compliance_status"].eq("COMPLIANCE_HOLD_DO_NOT_CALL_OR_TEXT")].copy()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total checked", len(gated))
    col2.metric("XLeads DNC + litigator clear", len(pending))
    col3.metric("Final approved", 0)
    col4.metric("Blocked / hold", len(gated))

    display = [
        "seller_name", "property_address", "first_found_phone", "xleads_screened_phone",
        "xleads_screened_phone_type", "xleads_screen_status", "compliance_status",
        "compliance_reason",
    ]

    st.write("### XLeads Clear - Still Do Not Call or Text")
    show_html(pending, display)
    st.download_button(
        "Download XLeads-Clear Pending Verification",
        pending.to_csv(index=False).encode("utf-8"),
        "war_room_xleads_clear_pending_verification.csv",
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
