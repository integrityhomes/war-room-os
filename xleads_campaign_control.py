from __future__ import annotations

from io import BytesIO
import re
from typing import Any, Iterable
from zipfile import BadZipFile, ZipFile

import pandas as pd


CLEAR = {"0", "false", "no", "clear", "cleared", "not listed", "not on dnc"}
BLOCK = {"1", "true", "yes", "dnc", "listed", "blocked", "stop", "do not call", "do not text"}
EMAIL_BLOCK = {"1", "true", "yes", "opted out", "opt-out", "unsubscribe", "unsubscribed", "suppressed", "complaint", "bounced"}

IDENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "first_name": ("FirstName", "First Name", "first_name"),
    "last_name": ("LastName", "Last Name", "last_name"),
    "property_street": ("PropertyAddress", "Property Address", "property_address"),
    "property_city": ("PropertyCity", "Property City", "property_city"),
    "property_state": ("PropertyState", "Property State", "property_state"),
    "property_zip": ("PropertyPostalCode", "PropertyZip", "Property ZIP", "property_zip"),
    "mailing_street": ("RecipientAddress", "MailingAddress", "Mailing Address", "mailing_address"),
    "mailing_city": ("RecipientCity", "MailingCity", "Mailing City"),
    "mailing_state": ("RecipientState", "MailingState", "Mailing State"),
    "mailing_zip": ("RecipientPostalCode", "MailingPostalCode", "Mailing ZIP"),
    "owner_type": ("OwnerType", "Owner Type"),
    "avm": ("AVM", "Avm"),
    "wholesale_value": ("WholesaleValue", "Wholesale Value"),
    "mls_status": ("MLS_Curr_Status", "MLS Current Status"),
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def normalize_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", clean_text(value).lower())


def unique_columns(df: pd.DataFrame) -> pd.DataFrame:
    return df.loc[:, ~df.columns.duplicated(keep="first")].copy()


def find_column(df: pd.DataFrame, aliases: Iterable[str]) -> str | None:
    lookup = {normalize_header(column): str(column) for column in df.columns}
    for alias in aliases:
        match = lookup.get(normalize_header(alias))
        if match is not None:
            return match
    return None


def series_from(df: pd.DataFrame, aliases: Iterable[str]) -> pd.Series:
    column = find_column(df, aliases)
    if column is None:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[column].fillna("").astype(str).map(clean_text)


def clean_phone(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(int(value)) if isinstance(value, float) and value.is_integer() else clean_text(value)
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".", 1)[0]
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def clean_email(value: Any) -> str:
    email = clean_text(value).lower()
    return email if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) else ""


def parse_phone_flag(value: Any) -> str:
    text = clean_text(value).lower()
    if text in BLOCK or "do not call" in text or "do not text" in text:
        return "BLOCKED"
    if text in CLEAR:
        return "CLEAR"
    return "UNKNOWN"


def parse_email_block(value: Any) -> bool:
    text = clean_text(value).lower()
    return text in EMAIL_BLOCK or "unsubscribe" in text or "opt out" in text or "opt-out" in text


def join_address(street: Any, city: Any, state: Any, postal: Any) -> str:
    return ", ".join(part for part in map(clean_text, (street, city, state, postal)) if part)


def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return unique_columns(pd.read_csv(BytesIO(data), encoding=encoding, low_memory=False))
        except Exception as exc:
            last_error = exc
    raise ValueError(f"The CSV could not be read: {last_error}")


def read_xleads_upload(filename: str, data: bytes) -> tuple[pd.DataFrame, str]:
    lower = clean_text(filename).lower()
    if lower.endswith(".csv"):
        return _read_csv_bytes(data), filename
    if not lower.endswith(".zip"):
        raise ValueError("Upload an XLeads .csv or .zip file.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            candidates = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".csv")]
            if not candidates:
                raise ValueError("The ZIP file does not contain a CSV.")
            chosen = max(candidates, key=lambda item: item.file_size)
            return _read_csv_bytes(archive.read(chosen)), chosen.filename
    except BadZipFile as exc:
        raise ValueError("The uploaded ZIP is damaged or invalid.") from exc


def detect_phone_groups(df: pd.DataFrame) -> list[dict[str, str]]:
    lookup = {normalize_header(column): str(column) for column in df.columns}
    groups: list[dict[str, str]] = []
    for column in df.columns:
        normalized = normalize_header(column)
        match = re.fullmatch(r"contact(\d+)phone(\d+)", normalized)
        if not match:
            continue
        groups.append({
            "phone": str(column),
            "type": lookup.get(f"{normalized}type", ""),
            "dnc": lookup.get(f"{normalized}dnc", ""),
            "litigator": lookup.get(f"{normalized}litigator", ""),
            "order": f"{int(match.group(1)):03d}-{int(match.group(2)):03d}",
        })
    return sorted(groups, key=lambda group: group["order"])


def detect_email_columns(df: pd.DataFrame) -> list[str]:
    ranked: list[tuple[str, str]] = []
    seen: set[str] = set()
    for column in df.columns:
        normalized = normalize_header(column)
        match = re.fullmatch(r"contact(\d+)email(\d+)", normalized)
        if match:
            ranked.append((f"{int(match.group(1)):03d}-{int(match.group(2)):03d}", str(column)))
            seen.add(str(column))
    for alias in ("Email", "email", "OwnerEmail", "owner_email"):
        column = find_column(df, (alias,))
        if column and column not in seen:
            ranked.append(("999-999", column))
            seen.add(column)
    return [column for _, column in sorted(ranked)]


def detect_internal_phone_blocks(df: pd.DataFrame) -> list[str]:
    tokens = ("optout", "donotcontact", "wrongnumber", "companydnc", "internaldnc")
    return [str(column) for column in df.columns if any(token in normalize_header(column) for token in tokens)]


def detect_email_block_columns(df: pd.DataFrame) -> list[str]:
    columns = []
    for column in df.columns:
        normalized = normalize_header(column)
        has_email = "email" in normalized
        has_block = any(token in normalized for token in ("optout", "unsubscribe", "suppress", "complaint", "bounce"))
        if has_email and has_block:
            columns.append(str(column))
    return columns


def is_returned_leadtrace(df: pd.DataFrame) -> bool:
    return bool(detect_phone_groups(df) or detect_email_columns(df))


def _identity_frame(raw_df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=raw_df.index)
    for target, aliases in IDENTITY_ALIASES.items():
        out[target] = series_from(raw_df, aliases)
    out["first_name"] = out["first_name"].map(clean_text)
    out["last_name"] = out["last_name"].map(clean_text)
    out["seller_name"] = (out["first_name"] + " " + out["last_name"]).str.strip()
    out["property_state"] = out["property_state"].str.upper()
    out["mailing_state"] = out["mailing_state"].str.upper()
    out["property_address"] = out.apply(lambda row: join_address(row["property_street"], row["property_city"], row["property_state"], row["property_zip"]), axis=1)
    out["mailing_address"] = out.apply(lambda row: join_address(row["mailing_street"], row["mailing_city"], row["mailing_state"], row["mailing_zip"]), axis=1)
    return out


def prepare_skiptrace_upload(raw_df: pd.DataFrame) -> pd.DataFrame:
    raw_df = unique_columns(raw_df)
    out = _identity_frame(raw_df)
    columns = [
        "first_name", "last_name", "seller_name", "property_street", "property_city", "property_state",
        "property_zip", "property_address", "mailing_street", "mailing_city", "mailing_state",
        "mailing_zip", "mailing_address", "owner_type", "avm", "wholesale_value", "mls_status",
    ]
    return out[columns].copy()


def _phone_result(row: pd.Series, groups: list[dict[str, str]], internal_blocks: list[str]) -> pd.Series:
    clear_phones: list[tuple[str, str]] = []
    blocked_count = 0
    unknown_count = 0
    first_found = ""
    internal_blocked = any(parse_phone_flag(row.get(column, "")) == "BLOCKED" for column in internal_blocks)

    for group in groups:
        candidate = clean_phone(row.get(group["phone"], ""))
        if not candidate:
            continue
        if not first_found:
            first_found = candidate
        dnc = parse_phone_flag(row.get(group["dnc"], "")) if group["dnc"] else "UNKNOWN"
        litigator = parse_phone_flag(row.get(group["litigator"], "")) if group["litigator"] else "UNKNOWN"
        if dnc == "CLEAR" and litigator == "CLEAR" and not internal_blocked:
            phone_type = clean_text(row.get(group["type"], "")) if group["type"] else ""
            if candidate not in [phone for phone, _ in clear_phones]:
                clear_phones.append((candidate, phone_type))
        elif dnc == "BLOCKED" or litigator == "BLOCKED" or internal_blocked:
            blocked_count += 1
        else:
            unknown_count += 1

    if clear_phones:
        action = "READY_FOR_XLEADS_PHONE"
        reason = "At least one phone has DNC=False and Litigator=False"
    elif unknown_count:
        action = "SCREENING_REVIEW"
        reason = "Phone found but DNC or litigator result is blank/unknown"
    elif blocked_count:
        action = "DNC_PHONE_HOLD"
        reason = "All usable phones are DNC, litigator, or internal opt-out blocked"
    else:
        action = "NO_VALID_PHONE"
        reason = "No valid 10-digit phone found"

    selected = clear_phones[:3]
    return pd.Series({
        "phone": selected[0][0] if len(selected) > 0 else "",
        "phone_2": selected[1][0] if len(selected) > 1 else "",
        "phone_3": selected[2][0] if len(selected) > 2 else "",
        "phone_type": selected[0][1] if selected else "",
        "first_found_phone": first_found,
        "phone_action": action,
        "phone_reason": reason,
        "clear_phone_count": len(clear_phones),
        "blocked_phone_count": blocked_count,
        "unknown_phone_count": unknown_count,
    })


def _email_result(row: pd.Series, email_columns: list[str], email_block_columns: list[str]) -> pd.Series:
    emails: list[str] = []
    for column in email_columns:
        candidate = clean_email(row.get(column, ""))
        if candidate and candidate not in emails:
            emails.append(candidate)

    blocked = any(parse_email_block(row.get(column, "")) for column in email_block_columns)
    if blocked:
        action = "EMAIL_SUPPRESSION_HOLD"
        reason = "Email opt-out, unsubscribe, suppression, complaint, or bounce flag found"
        selected: list[str] = []
    elif emails:
        action = "READY_FOR_XLEADS_EMAIL"
        reason = "Valid email found; phone DNC does not remove it from the email lane"
        selected = emails[:3]
    else:
        action = "NO_VALID_EMAIL"
        reason = "No valid email found"
        selected = []

    return pd.Series({
        "email": selected[0] if len(selected) > 0 else "",
        "email_2": selected[1] if len(selected) > 1 else "",
        "email_3": selected[2] if len(selected) > 2 else "",
        "email_action": action,
        "email_reason": reason,
        "valid_email_count": len(emails),
    })


def analyze_returned_export(raw_df: pd.DataFrame, campaign_tag: str = "xleads-campaign") -> pd.DataFrame:
    raw_df = unique_columns(raw_df)
    out = _identity_frame(raw_df)
    phone_groups = detect_phone_groups(raw_df)
    email_columns = detect_email_columns(raw_df)
    internal_blocks = detect_internal_phone_blocks(raw_df)
    email_blocks = detect_email_block_columns(raw_df)

    phone_results = raw_df.apply(lambda row: _phone_result(row, phone_groups, internal_blocks), axis=1)
    email_results = raw_df.apply(lambda row: _email_result(row, email_columns, email_blocks), axis=1)
    out = pd.concat([out, phone_results, email_results], axis=1)

    out["phone_ready"] = out["phone_action"].eq("READY_FOR_XLEADS_PHONE")
    out["email_ready"] = out["email_action"].eq("READY_FOR_XLEADS_EMAIL")
    out["campaign_ready"] = out["phone_ready"] | out["email_ready"]
    out["email_only"] = out["email_ready"] & ~out["phone_ready"]

    def campaign_action(row: pd.Series) -> str:
        if row["phone_ready"] and row["email_ready"]:
            return "READY_PHONE_AND_EMAIL"
        if row["phone_ready"]:
            return "READY_PHONE_ONLY"
        if row["email_ready"]:
            return "READY_EMAIL_ONLY"
        if row["phone_action"] == "SCREENING_REVIEW":
            return "PHONE_SCREENING_REVIEW"
        if row["phone_action"] == "DNC_PHONE_HOLD":
            return "PHONE_DNC_HOLD"
        return "NO_USABLE_CONTACT"

    out["campaign_action"] = out.apply(campaign_action, axis=1)
    out["campaign_tag"] = re.sub(r"[^a-z0-9]+", "-", clean_text(campaign_tag).lower()).strip("-") or "xleads-campaign"
    out["xleads_tags"] = out.apply(lambda row: ",".join(tag for tag in [
        "war-room-processed",
        row["campaign_tag"],
        "phone-ready" if row["phone_ready"] else "",
        "email-ready" if row["email_ready"] else "",
        "email-only" if row["email_only"] else "",
        "phone-dnc-hold" if row["phone_action"] == "DNC_PHONE_HOLD" else "",
        "phone-screening-review" if row["phone_action"] == "SCREENING_REVIEW" else "",
    ] if tag), axis=1)
    out["audit_id"] = [f"war-room-{index + 1:06d}" for index in range(len(out))]
    return out


def build_report(queue: pd.DataFrame) -> dict[str, int]:
    return {
        "total": int(len(queue)),
        "campaign_ready": int(queue["campaign_ready"].sum()),
        "phone_ready": int(queue["phone_ready"].sum()),
        "email_ready": int(queue["email_ready"].sum()),
        "email_only": int(queue["email_only"].sum()),
        "dnc_phone_hold": int((queue["phone_action"] == "DNC_PHONE_HOLD").sum()),
        "screening_review": int((queue["phone_action"] == "SCREENING_REVIEW").sum()),
        "no_contact": int((queue["campaign_action"] == "NO_USABLE_CONTACT").sum()),
    }


CAMPAIGN_COLUMNS = [
    "audit_id", "first_name", "last_name", "seller_name", "phone", "phone_2", "phone_3",
    "phone_type", "email", "email_2", "email_3", "mailing_street", "mailing_city",
    "mailing_state", "mailing_zip", "mailing_address", "property_street", "property_city",
    "property_state", "property_zip", "property_address", "owner_type", "avm", "wholesale_value",
    "mls_status", "phone_action", "phone_reason", "email_action", "email_reason",
    "campaign_action", "xleads_tags", "campaign_tag",
]


def campaign_export(queue: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in CAMPAIGN_COLUMNS if column in queue.columns]
    return queue.loc[queue["campaign_ready"], columns].copy()


def phone_export(queue: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in CAMPAIGN_COLUMNS if column in queue.columns]
    return queue.loc[queue["phone_ready"], columns].copy()


def email_export(queue: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in CAMPAIGN_COLUMNS if column in queue.columns]
    return queue.loc[queue["email_ready"], columns].copy()


def review_export(queue: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in CAMPAIGN_COLUMNS if column in queue.columns]
    return queue.loc[~queue["campaign_ready"], columns].copy()
