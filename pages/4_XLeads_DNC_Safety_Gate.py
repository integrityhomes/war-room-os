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


def first_matching_column(df: pd.DataFrame, names: list[str]) -> str | None:
    lookup = {norm(column): column for column in df.columns}
    for name in names:
        match = lookup.get(norm(name))
        if match is not None:
            return match
    return None


def text_series(df: pd.DataFrame, names: list[str]) -> pd.Series:
    column = first_matching_column(df, names)
    if column is None:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str)


def detect_phone_groups(df: pd.DataFrame) -> list[dict[str, str]]:
    lookup = {norm(column): str(column) for column in df.columns}
    groups: list[dict[str, str]] = []

    for column in df.columns:
        normalized = norm(column)
        if not re.fullmatch(r"contact\d+phone_\d+", normalized):
            continue

        groups.append(
            {
                "phone": str(column),
                "type": lookup.get(f"{normalized}_type", ""),
                "dnc": lookup.get(f"{normalized}_dnc", ""),
                "litigator": lookup.get(f"{normalized}_litigator", ""),
            }
        )

    def sort_key(group: dict[str, str]) -> tuple[int, int]:
        match = re.fullmatch(r"contact(\d+)phone_(\d+)", norm(group["phone"]))
        return (int(match.group(1)), int(match.group(2))) if match else (999, 999)

    return sorted(groups, key=sort_key)


def explicit_dnc_columns(df: pd.DataFrame) -> dict[str, list[str]]:
    columns = [str(column) for column in df.columns]

    def choose(tokens: list[str]) -> list[str]:
        return [
            column
            for column in columns
            if "dnc" in norm(column) and any(token in norm(column) for token in tokens)
        ]

    return {
        "national": choose(["national", "federal"]),
        "state": choose(["state"]),
        "company": choose(["company", "internal", "entity", "specific"]),
    }


def combine_status(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    if not columns:
        return pd.Series(["UNKNOWN"] * len(df), index=df.index, dtype="object")

    def combine(row: pd.Series) -> str:
        statuses = [parse_flag(value) for value in row]
        if "BLOCKED" in statuses:
            return "BLOCKED"
        if statuses and all(status == "CLEAR" for status in statuses):
            return "CLEAR"
        return "UNKNOWN"

    return df[columns].fillna("").astype(str).apply(combine, axis=1)


def schema_report(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for column in df.columns:
        name = norm(column)
        if not any(token in name for token in ["phone", "mobile", "cell", "tel", "dnc", "litigator", "opt_out"]):
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


def evaluate_row(row: pd.Series, groups: list[dict[str, str]]) -> pd.Series:
    any_valid_phone = False
    any_dnc_blocked = False
    any_litigator_blocked = False
    any_unknown_screen = False
    first_found_phone = ""
    first_clear_phone = ""
    first_clear_type = ""

    for group in groups:
        candidate = normalize_phone(row.get(group["phone"], ""))
        if not candidate:
            continue

        any_valid_phone = True
        if not first_found_phone:
            first_found_phone = candidate

        dnc_status = parse_flag(row.get(group["dnc"], "")) if group["dnc"] else "UNKNOWN"
        litigator_status = parse_flag(row.get(group["litigator"], "")) if group["litigator"] else "UNKNOWN"

        if dnc_status == "BLOCKED":
            any_dnc_blocked = True
        if litigator_status == "BLOCKED":
            any_litigator_blocked = True
        if dnc_status == "UNKNOWN" or litigator_status == "UNKNOWN":
            any_unknown_screen = True

        if dnc_status == "CLEAR" and litigator_status == "CLEAR" and not first_clear_phone:
            first_clear_phone = candidate
            first_clear_type = clean(row.get(group["type"], "")) if group["type"] else ""

    if first_clear_phone:
        xleads_status = "XLEADS_DNC_AND_LITIGATOR_CLEAR"
    elif not any_valid_phone:
        xleads_status = "NO_VALID_PHONE"
    elif any_dnc_blocked:
        xleads_status = "XLEADS_DNC_BLOCKED"
    elif any_litigator_blocked:
        xleads_status = "XLEADS_LITIGATOR_BLOCKED"
    elif any_unknown_screen:
        xleads_status = "XLEADS_SCREEN_UNKNOWN"
    else:
        xleads_status = "NO_CLEAR_PHONE"

    return pd.Series(
        {
            "first_found_phone": first_found_phone,
            "xleads_screened_phone": first_clear_phone,
            "xleads_screened_phone_type": first_clear_type,
            "xleads_screen_status": xleads_status,
        }
    )


def apply_gate(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    output = df.copy()
    output["seller_name"] = text_series(output, ["seller_name", "seller name", "owner_name", "owner name", "name"])
    output["property_address"] = text_series(output, ["property_address", "property address", "address"])
    output["mailing_address"] = text_series(output, ["mailing_address", "mailing address", "owner_address", "owner address"])

    groups = detect_phone_groups(output)
    evaluated = output.apply(lambda row: evaluate_row(row, groups), axis=1)
    output = pd.concat([output, evaluated], axis=1)

    explicit = explicit_dnc_columns(output)
    output["national_dnc_status"] = combine_status(output, explicit["national"])
    output["state_dnc_status"] = combine_status(output, explicit["state"])
    output["company_dnc_status"] = combine_status(output, explicit["company"])

    opt_out_columns = [
        str(column)
        for column in output.columns
        if any(token in norm(column) for token in ["opt_out", "do_not_contact", "wrong_number"])
    ]
    output["prior_opt_out"] = False
    output["wrong_number"] = False
    for column in opt_out_columns:
        blocked = output[column].fillna("").astype(str).map(lambda value: parse_flag(value) == "BLOCKED")
        if "wrong_number" in norm(column):
            output["wrong_number"] = output["wrong_number"] | blocked
        else:
            output["prior_opt_out"] = output["prior_opt_out"] | blocked

    xleads_clear = output["xleads_screen_status"].eq("XLEADS_DNC_AND_LITIGATOR_CLEAR")
    final_clear = (
        xleads_clear
        & output["national_dnc_status"].eq("CLEAR")
        & output["state_dnc_status"].eq("CLEAR")
        & output["company_dnc_status"].eq("CLEAR")
        & ~output["prior_opt_out"]
        & ~output["wrong_number"]
    )

    output["compliance_status"] = "COMPLIANCE_HOLD_DO_NOT_CALL_OR_TEXT"
    output.loc[xleads_clear, "compliance_status"] = "XLEADS_CLEAR_PENDING_DNC_SCOPE_CONFIRMATION"
    output.loc[final_clear, "compliance_status"] = "APPROVED_FOR_CONTACT_REVIEW"

    def reason(row: pd.Series) -> str:
        reasons: list[str] = []
        if row["xleads_screen_status"] != "XLEADS_DNC_AND_LITIGATOR_CLEAR":
            reasons.append(row["xleads_screen_status"])
        if row["national_dnc_status"] != "CLEAR":
            reasons.append("NATIONAL_DNC_NOT_CONFIRMED")
        if row["state_dnc_status"] != "CLEAR":
            reasons.append("STATE_DNC_NOT_CONFIRMED")
        if row["company_dnc_status"] != "CLEAR":
            reasons.append("COMPANY_DNC_NOT_CONFIRMED")
        if row["prior_opt_out"]:
            reasons.append("PRIOR_OPT_OUT")
        if row["wrong_number"]:
            reasons.append("WRONG_NUMBER")
        return "APPROVED" if not reasons else " | ".join(reasons)

    output["compliance_reason"] = output.apply(reason, axis=1)
    output["phone"] = ""
    output.loc[final_clear, "phone"] = output.loc[final_clear, "xleads_screened_phone"]
    output["xleads_action"] = "HOLD_COMPLIANCE"
    output.loc[final_clear, "xleads_action"] = "READY_FOR_XLEADS_CAMPAIGN"
    output["call_lane"] = "Compliance Hold / No Call"
    output.loc[final_clear, "call_lane"] = "Eligible After Human Review"

    for column in ["must_call", "ai_call_allowed", "human_call_task_allowed"]:
        if column not in output.columns:
            output[column] = False
        output.loc[~final_clear, column] = False

    return output, {
        "phone_groups": groups,
        "national_dnc_columns": explicit["national"],
        "state_dnc_columns": explicit["state"],
        "company_dnc_columns": explicit["company"],
    }


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


st.title("War Room OS")
st.subheader("XLeads Phone-by-Phone DNC + Litigator Safety Gate")
st.error(
    "Fail-closed rule: DNC=True, Litigator=True, blank screening, or unknown screening is blocked. "
    "XLeads DNC=False and Litigator=False only passes the XLeads screening stage. "
    "Actual contact remains blocked until federal/state/company DNC scope is confirmed."
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
with st.expander("Inspect detected XLeads phone, DNC, and litigator columns", expanded=True):
    if report.empty:
        st.warning("No phone, DNC, or litigator columns were detected.")
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
    pending = gated[gated["compliance_status"].eq("XLEADS_CLEAR_PENDING_DNC_SCOPE_CONFIRMATION")].copy()
    hold = gated[gated["compliance_status"].eq("COMPLIANCE_HOLD_DO_NOT_CALL_OR_TEXT")].copy()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total checked", len(gated))
    col2.metric("XLeads DNC + litigator clear", len(pending) + len(approved))
    col3.metric("Final approved", len(approved))
    col4.metric("Blocked / hold", len(hold) + len(pending))

    st.write("### Detected XLeads phone groups")
    st.json(detected)

    display = [
        "seller_name", "property_address", "first_found_phone",
        "xleads_screened_phone", "xleads_screened_phone_type",
        "xleads_screen_status", "national_dnc_status",
        "state_dnc_status", "company_dnc_status",
        "compliance_status", "compliance_reason",
    ]

    st.write("### Final Approved - Human Review Required")
    show_html(approved, display)
    st.download_button(
        "Download Final Approved Queue",
        approved.to_csv(index=False).encode("utf-8"),
        "war_room_final_approved_queue.csv",
        "text/csv",
    )

    st.write("### XLeads Clear - Still Do Not Call or Text")
    st.caption(
        "These phones show DNC=False and Litigator=False in XLeads, but remain blocked until the scope of XLeads' DNC flag is confirmed for federal, state, and company lists."
    )
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
