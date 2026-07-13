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


def normalize_phone(value) -> str:
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = clean(value)
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


def first_col(df: pd.DataFrame, names: list[str]) -> str | None:
    lookup = {norm(c): c for c in df.columns}
    for name in names:
        found = lookup.get(norm(name))
        if found is not None:
            return found
    return None


def text_series(df: pd.DataFrame, names: list[str]) -> pd.Series:
    col = first_col(df, names)
    if col is None:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[col].fillna("").astype(str)


def detect_phone_groups(df: pd.DataFrame) -> list[dict[str, str]]:
    lookup = {norm(c): str(c) for c in df.columns}
    groups: list[dict[str, str]] = []
    for column in df.columns:
        n = norm(column)
        if not re.fullmatch(r"contact\d+phone_\d+", n):
            continue
        groups.append({
            "phone": str(column),
            "type": lookup.get(f"{n}_type", ""),
            "dnc": lookup.get(f"{n}_dnc", ""),
            "litigator": lookup.get(f"{n}_litigator", ""),
        })
    return groups


def schema_report(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in df.columns:
        n = norm(column)
        if not any(t in n for t in ["phone", "dnc", "litigator", "opt_out", "wrong_number"]):
            continue
        vals = [clean(v) for v in df[column].tolist() if clean(v)]
        rows.append({
            "column": str(column),
            "nonblank_rows": len(vals),
            "sample_values": " | ".join(list(dict.fromkeys(vals))[:3]),
        })
    return pd.DataFrame(rows)


def evaluate_row(row: pd.Series, groups: list[dict[str, str]]) -> pd.Series:
    first_found = ""
    first_clear = ""
    first_type = ""
    saw_valid = False
    saw_dnc_block = False
    saw_litigator_block = False
    saw_unknown = False

    for group in groups:
        candidate = normalize_phone(row.get(group["phone"], ""))
        if not candidate:
            continue
        saw_valid = True
        if not first_found:
            first_found = candidate
        dnc_status = parse_flag(row.get(group["dnc"], "")) if group["dnc"] else "UNKNOWN"
        lit_status = parse_flag(row.get(group["litigator"], "")) if group["litigator"] else "UNKNOWN"
        saw_dnc_block = saw_dnc_block or dnc_status == "BLOCKED"
        saw_litigator_block = saw_litigator_block or lit_status == "BLOCKED"
        saw_unknown = saw_unknown or dnc_status == "UNKNOWN" or lit_status == "UNKNOWN"
        if dnc_status == "CLEAR" and lit_status == "CLEAR" and not first_clear:
            first_clear = candidate
            first_type = clean(row.get(group["type"], "")) if group["type"] else ""

    if first_clear:
        status = "XLEADS_DNC_AND_LITIGATOR_CLEAR"
    elif not saw_valid:
        status = "NO_VALID_PHONE"
    elif saw_dnc_block:
        status = "XLEADS_DNC_BLOCKED"
    elif saw_litigator_block:
        status = "XLEADS_LITIGATOR_BLOCKED"
    elif saw_unknown:
        status = "XLEADS_SCREEN_UNKNOWN"
    else:
        status = "NO_CLEAR_PHONE"

    return pd.Series({
        "first_found_phone": first_found,
        "xleads_screened_phone": first_clear,
        "xleads_screened_phone_type": first_type,
        "xleads_screen_status": status,
    })


def apply_gate(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    output["seller_name"] = text_series(output, ["seller_name", "seller name", "owner_name", "owner name", "name"])
    output["property_address"] = text_series(output, ["property_address", "property address", "address"])
    groups = detect_phone_groups(output)
    evaluated = output.apply(lambda r: evaluate_row(r, groups), axis=1)
    output = pd.concat([output, evaluated], axis=1)

    output["national_dnc_status"] = "UNKNOWN"
    output["state_dnc_status"] = "UNKNOWN"
    output["company_dnc_status"] = "UNKNOWN"
    output["prior_opt_out"] = False
    output["wrong_number"] = False

    for column in output.columns:
        n = norm(column)
        if "opt_out" in n or "do_not_contact" in n:
            output["prior_opt_out"] = output["prior_opt_out"] | output[column].fillna("").astype(str).map(lambda v: parse_flag(v) == "BLOCKED")
        if "wrong_number" in n:
            output["wrong_number"] = output["wrong_number"] | output[column].fillna("").astype(str).map(lambda v: parse_flag(v) == "BLOCKED")

    xleads_clear = output["xleads_screen_status"].eq("XLEADS_DNC_AND_LITIGATOR_CLEAR")
    output["compliance_status"] = "COMPLIANCE_HOLD_DO_NOT_CALL_OR_TEXT"
    output.loc[xleads_clear, "compliance_status"] = "XLEADS_CLEAR_PENDING_DNC_SCOPE_CONFIRMATION"
    output["phone"] = ""
    output["xleads_action"] = "HOLD_COMPLIANCE"
    output["call_lane"] = "Compliance Hold / No Call"
    for column in ["must_call", "ai_call_allowed", "human_call_task_allowed"]:
        if column not in output.columns:
            output[column] = False
        output[column] = False

    def reason(row: pd.Series) -> str:
        reasons = []
        if row["xleads_screen_status"] != "XLEADS_DNC_AND_LITIGATOR_CLEAR":
            reasons.append(row["xleads_screen_status"])
        reasons += ["NATIONAL_DNC_NOT_CONFIRMED", "STATE_DNC_NOT_CONFIRMED", "COMPANY_DNC_NOT_CONFIRMED"]
        if row["prior_opt_out"]:
            reasons.append("PRIOR_OPT_OUT")
        if row["wrong_number"]:
            reasons.append("WRONG_NUMBER")
        return " | ".join(reasons)

    output["compliance_reason"] = output.apply(reason, axis=1)
    return output


def show_html(df: pd.DataFrame, columns: list[str], limit: int = 100) -> None:
    if df.empty:
        st.caption("No records in this queue.")
        return
    view = df[[c for c in columns if c in df.columns]].head(limit).copy()
    for c in view.columns:
        view[c] = view[c].fillna("").astype(str)
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
    "DNC=False and Litigator=False only passes XLeads screening. Contact remains blocked until federal, state, and company DNC scope is confirmed."
)

uploaded = st.file_uploader("Upload the XLeads export CSV", type=["csv"], key="xleads_dnc_upload")
source_df = pd.read_csv(uploaded) if uploaded is not None else st.session_state.get("scored_df")
if source_df is None:
    st.warning("Upload the XLeads CSV here, or run Intelligent Lead Ranking first.")
    st.stop()

report = schema_report(source_df)
with st.expander("Inspect detected XLeads phone, DNC, and litigator columns", expanded=True):
    show_html(report, ["column", "nonblank_rows", "sample_values"], limit=200)
    st.download_button("Download XLeads Column Report", report.to_csv(index=False).encode("utf-8"), "xleads_column_report.csv", "text/csv")

if st.button("Apply Hard DNC Safety Gate", type="primary"):
    gated = apply_gate(source_df)
    st.session_state["scored_df"] = gated
    pending = gated[gated["compliance_status"].eq("XLEADS_CLEAR_PENDING_DNC_SCOPE_CONFIRMATION")].copy()
    hold = gated[gated["compliance_status"].eq("COMPLIANCE_HOLD_DO_NOT_CALL_OR_TEXT")].copy()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total checked", len(gated))
    c2.metric("XLeads DNC + litigator clear", len(pending))
    c3.metric("Final approved", 0)
    c4.metric("Blocked / hold", len(gated))

    display = ["seller_name", "property_address", "first_found_phone", "xleads_screened_phone", "xleads_screened_phone_type", "xleads_screen_status", "compliance_status", "compliance_reason"]

    st.write("### XLeads Clear - Still Do Not Call or Text")
    show_html(pending, display)
    st.download_button("Download XLeads-Clear Pending Verification", pending.to_csv(index=False).encode("utf-8"), "war_room_xleads_clear_pending_verification.csv", "text/csv")

    st.write("### Compliance Hold - Do Not Call or Text")
    show_html(hold, display)
    st.download_button("Download Compliance Hold List", hold.to_csv(index=False).encode("utf-8"), "war_room_compliance_hold_do_not_call_or_text.csv", "text/csv")
