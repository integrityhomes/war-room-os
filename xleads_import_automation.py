from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import re
from typing import Any, Iterable
from zipfile import BadZipFile, ZipFile

import pandas as pd
import requests

DEFAULT_SOURCE_TAG = "leadpipes-export"
DEFAULT_API_BASE = "https://services.leadconnectorhq.com"
DEFAULT_API_VERSION = "2021-07-28"

ALIASES: dict[str, tuple[str, ...]] = {
    "first_name": ("FirstName", "First Name", "first_name"),
    "last_name": ("LastName", "Last Name", "last_name"),
    "email": ("Contact1Email_1", "Contact1Email1", "Email", "email"),
    "property_street": ("PropertyAddress", "Property Address", "property_address"),
    "property_city": ("PropertyCity", "Property City", "property_city"),
    "property_state": ("PropertyState", "Property State", "property_state"),
    "property_zip": ("PropertyPostalCode", "PropertyZip", "Property ZIP", "property_zip"),
    "mailing_street": ("RecipientAddress", "MailingAddress", "Mailing Address"),
    "mailing_city": ("RecipientCity", "MailingCity", "Mailing City"),
    "mailing_state": ("RecipientState", "MailingState", "Mailing State"),
    "mailing_zip": ("RecipientPostalCode", "MailingPostalCode", "Mailing ZIP"),
    "owner_type": ("OwnerType", "Owner Type"),
    "avm": ("AVM", "Avm"),
    "wholesale_value": ("WholesaleValue", "Wholesale Value"),
    "mls_status": ("MLS_Curr_Status", "MLS Current Status"),
    "mls_list_price": ("MLS_Curr_ListPrice", "MLS Current List Price"),
    "mls_agent_name": ("MLS_Curr_ListAgentName", "MLS Current List Agent Name"),
    "mls_agent_phone": ("MLS_Curr_ListAgentPhone", "MLS Current List Agent Phone"),
    "mls_agent_email": ("MLS_Curr_ListAgentEmail", "MLS Current List Agent Email"),
}

CLEAR = {"0", "false", "no", "clear", "cleared", "not listed", "not on dnc"}
BLOCK = {"1", "true", "yes", "dnc", "listed", "blocked", "stop", "do not call", "do not text"}


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


def parse_flag(value: Any) -> str:
    text = clean_text(value).lower()
    if text in BLOCK or "do not call" in text or "do not text" in text:
        return "BLOCKED"
    if text in CLEAR:
        return "CLEAR"
    return "UNKNOWN"


def join_address(street: Any, city: Any, state: Any, postal: Any) -> str:
    return ", ".join(part for part in map(clean_text, (street, city, state, postal)) if part)


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean_text(value).lower()).strip("-")[:80] or "xleads-import"


def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            frame = pd.read_csv(BytesIO(data), encoding=encoding, low_memory=False)
            return frame.loc[:, ~frame.columns.duplicated(keep="first")].copy()
        except Exception as exc:
            last_error = exc
    raise ValueError(f"The CSV could not be read: {last_error}")


def read_xleads_upload(filename: str, data: bytes) -> tuple[pd.DataFrame, str]:
    lower = clean_text(filename).lower()
    if lower.endswith(".csv"):
        return _read_csv_bytes(data), filename
    if not lower.endswith(".zip"):
        raise ValueError("Upload an XLeads .csv or .zip export.")
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
        base = normalized
        groups.append({
            "phone": str(column),
            "type": lookup.get(f"{base}type", ""),
            "dnc": lookup.get(f"{base}dnc", ""),
            "litigator": lookup.get(f"{base}litigator", ""),
            "order": f"{int(match.group(1)):03d}-{int(match.group(2)):03d}",
        })
    return sorted(groups, key=lambda group: group["order"])


def choose_phone(row: pd.Series, groups: list[dict[str, str]]) -> pd.Series:
    first_valid = ""
    first_type = ""
    first_clear = ""
    first_clear_type = ""
    blocked_found = False
    unknown_found = False

    for group in groups:
        candidate = clean_phone(row.get(group["phone"], ""))
        if not candidate:
            continue
        if not first_valid:
            first_valid = candidate
            first_type = clean_text(row.get(group["type"], "")) if group["type"] else ""
        dnc = parse_flag(row.get(group["dnc"], "")) if group["dnc"] else "UNKNOWN"
        litigator = parse_flag(row.get(group["litigator"], "")) if group["litigator"] else "UNKNOWN"
        blocked_found = blocked_found or dnc == "BLOCKED" or litigator == "BLOCKED"
        unknown_found = unknown_found or dnc == "UNKNOWN" or litigator == "UNKNOWN"
        if dnc == "CLEAR" and litigator == "CLEAR" and not first_clear:
            first_clear = candidate
            first_clear_type = clean_text(row.get(group["type"], "")) if group["type"] else ""

    if first_clear:
        action = "READY_TO_SYNC"
        reason = "Valid phone with DNC=False and Litigator=False"
    elif first_valid and blocked_found:
        action = "DNC_HOLD"
        reason = "All usable phones are DNC/litigator blocked or not clearly screened"
    elif first_valid and unknown_found:
        action = "SCREENING_REVIEW"
        reason = "Phone found but DNC/litigator result is blank or unknown"
    elif first_valid:
        action = "SCREENING_REVIEW"
        reason = "Phone found but no clearly screened phone is available"
    else:
        action = "NEEDS_CONTACT_MATCH"
        reason = "No valid phone found"

    return pd.Series({
        "phone": first_clear,
        "phone_2": first_valid if first_valid != first_clear else "",
        "phone_type": first_clear_type or first_type,
        "phone_screen_action": action,
        "phone_screen_reason": reason,
    })


def prepare_sync_dataframe(raw_df: pd.DataFrame, campaign_tag: str) -> pd.DataFrame:
    if raw_df.empty:
        raise ValueError("The XLeads export has no rows.")

    raw_df = raw_df.loc[:, ~raw_df.columns.duplicated(keep="first")].copy()
    out = pd.DataFrame(index=raw_df.index)
    for target, aliases in ALIASES.items():
        out[target] = series_from(raw_df, aliases)

    out["first_name"] = out["first_name"].map(clean_text)
    out["last_name"] = out["last_name"].map(clean_text)
    out["seller_name"] = (out["first_name"] + " " + out["last_name"]).str.strip()
    out["email"] = out["email"].map(clean_email)
    out["property_state"] = out["property_state"].str.upper()
    out["mailing_state"] = out["mailing_state"].str.upper()
    out["property_address"] = out.apply(lambda row: join_address(row["property_street"], row["property_city"], row["property_state"], row["property_zip"]), axis=1)
    out["mailing_address"] = out.apply(lambda row: join_address(row["mailing_street"], row["mailing_city"], row["mailing_state"], row["mailing_zip"]), axis=1)

    phone_review = raw_df.apply(lambda row: choose_phone(row, detect_phone_groups(raw_df)), axis=1)
    out = pd.concat([out, phone_review], axis=1)

    out["campaign_tag"] = safe_slug(campaign_tag)
    out["source_tag"] = DEFAULT_SOURCE_TAG
    out["source"] = "XLeads Lead Trace Export"

    email_key = out["email"].where(out["email"].ne(""), "")
    name_mail_key = out["seller_name"].str.lower().str.replace(r"[^a-z0-9]", "", regex=True) + "|" + out["mailing_address"].str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    out["contact_key"] = out["phone"].where(out["phone"].ne(""), email_key)
    out["contact_key"] = out["contact_key"].where(out["contact_key"].ne(""), name_mail_key)
    out["property_key"] = out["property_address"].str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    out["owner_property_key"] = out["contact_key"] + "|" + out["property_key"]
    out["duplicate_owner_property"] = out["owner_property_key"].duplicated(keep="first") & out["owner_property_key"].ne("|")

    property_counts = out.loc[out["contact_key"].ne("") & out["property_key"].ne(""), ["contact_key", "property_key"]].drop_duplicates().groupby("contact_key")["property_key"].nunique()
    out["property_count_for_contact"] = out["contact_key"].map(property_counts).fillna(0).astype(int)
    out["multi_property_review"] = out["property_count_for_contact"] > 1

    out["sync_action"] = out["phone_screen_action"]
    out["sync_reason"] = out["phone_screen_reason"]
    out.loc[out["phone"].eq("") & out["email"].ne("") & out["sync_action"].eq("NEEDS_CONTACT_MATCH"), ["sync_action", "sync_reason"]] = ["READY_TO_SYNC", "Valid email; no callable phone"]
    out.loc[out["property_address"].eq(""), ["sync_action", "sync_reason"]] = ["NEEDS_PROPERTY_DATA", "Property address is missing"]
    out.loc[out["multi_property_review"] & ~out["duplicate_owner_property"], ["sync_action", "sync_reason"]] = ["MULTI_PROPERTY_REVIEW", "One contact is tied to multiple properties"]
    out.loc[out["duplicate_owner_property"], ["sync_action", "sync_reason"]] = ["SUPPRESS_DUPLICATE", "Duplicate owner and property row"]

    out["safe_to_sync"] = out["sync_action"].eq("READY_TO_SYNC")
    out["dnc_hold"] = out["sync_action"].eq("DNC_HOLD")
    out["screening_review"] = out["sync_action"].eq("SCREENING_REVIEW")
    out["crm_tags"] = out.apply(_build_tags, axis=1)
    out["audit_id"] = [f"xleads-{index + 1:06d}" for index in range(len(out))]
    return out


def _build_tags(row: pd.Series) -> str:
    tags = [DEFAULT_SOURCE_TAG, clean_text(row.get("campaign_tag"))]
    mapping = {
        "DNC_HOLD": "xleads-dnc-hold",
        "SCREENING_REVIEW": "xleads-screening-review",
        "MULTI_PROPERTY_REVIEW": "xleads-multi-property-review",
        "NEEDS_CONTACT_MATCH": "xleads-needs-contact-match",
        "NEEDS_PROPERTY_DATA": "xleads-needs-property-data",
    }
    tag = mapping.get(clean_text(row.get("sync_action")))
    if tag:
        tags.append(tag)
    return ",".join(dict.fromkeys(value for value in tags if value))


def build_report(queue: pd.DataFrame) -> dict[str, int]:
    return {
        "total_rows": int(len(queue)),
        "ready_to_sync": int(queue["safe_to_sync"].sum()),
        "dnc_holds": int((queue["sync_action"] == "DNC_HOLD").sum()),
        "screening_review": int((queue["sync_action"] == "SCREENING_REVIEW").sum()),
        "multi_property_review": int((queue["sync_action"] == "MULTI_PROPERTY_REVIEW").sum()),
        "duplicates_suppressed": int((queue["sync_action"] == "SUPPRESS_DUPLICATE").sum()),
        "missing_contact_match": int((queue["sync_action"] == "NEEDS_CONTACT_MATCH").sum()),
        "missing_property": int((queue["sync_action"] == "NEEDS_PROPERTY_DATA").sum()),
    }


@dataclass(frozen=True)
class HighLevelConfig:
    token: str
    location_id: str
    property_address_field: str
    property_city_field: str
    property_state_field: str
    property_zip_field: str
    api_base: str = DEFAULT_API_BASE
    api_version: str = DEFAULT_API_VERSION

    @property
    def configured(self) -> bool:
        return all(clean_text(value) for value in (self.token, self.location_id, self.property_address_field, self.property_city_field, self.property_state_field, self.property_zip_field))


def _custom_field(field_id_or_key: str, value: Any) -> dict[str, str]:
    field = clean_text(field_id_or_key)
    key = "id" if re.fullmatch(r"[A-Za-z0-9_-]{10,}", field) else "key"
    return {key: field, "field_value": clean_text(value)}


def build_highlevel_payload(row: pd.Series, config: HighLevelConfig) -> dict[str, Any]:
    tags = [tag.strip() for tag in clean_text(row.get("crm_tags")).split(",") if tag.strip()]
    payload: dict[str, Any] = {
        "locationId": config.location_id,
        "firstName": clean_text(row.get("first_name")),
        "lastName": clean_text(row.get("last_name")),
        "name": clean_text(row.get("seller_name")),
        "phone": clean_text(row.get("phone")),
        "email": clean_text(row.get("email")),
        "address1": clean_text(row.get("mailing_street")),
        "city": clean_text(row.get("mailing_city")),
        "state": clean_text(row.get("mailing_state")),
        "postalCode": clean_text(row.get("mailing_zip")),
        "source": "XLeads Lead Trace Export",
        "tags": tags,
        "customFields": [
            _custom_field(config.property_address_field, row.get("property_street")),
            _custom_field(config.property_city_field, row.get("property_city")),
            _custom_field(config.property_state_field, row.get("property_state")),
            _custom_field(config.property_zip_field, row.get("property_zip")),
        ],
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


class HighLevelClient:
    def __init__(self, config: HighLevelConfig, timeout: int = 30) -> None:
        if not config.configured:
            raise ValueError("Ninja CRM sync secrets are incomplete.")
        self.config = config
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.token}", "Content-Type": "application/json", "Accept": "application/json", "Version": self.config.api_version}

    def upsert_contact(self, row: pd.Series) -> dict[str, Any]:
        response = requests.post(f"{self.config.api_base.rstrip('/')}/contacts/upsert", headers=self.headers, json=build_highlevel_payload(row, self.config), timeout=self.timeout)
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text[:1000]}
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"HighLevel upsert failed ({response.status_code}): {json.dumps(body)[:1000]}")
        return body


def sync_safe_rows(queue: pd.DataFrame, client: HighLevelClient) -> pd.DataFrame:
    results = []
    for _, row in queue[queue["safe_to_sync"]].iterrows():
        try:
            response = client.upsert_contact(row)
            contact = response.get("contact", response) if isinstance(response, dict) else {}
            results.append({"audit_id": row["audit_id"], "seller_name": row["seller_name"], "phone": row["phone"], "property_address": row["property_address"], "sync_result": "SUCCESS", "contact_id": clean_text(contact.get("id", "")) if isinstance(contact, dict) else "", "error": ""})
        except Exception as exc:
            results.append({"audit_id": row["audit_id"], "seller_name": row["seller_name"], "phone": row["phone"], "property_address": row["property_address"], "sync_result": "FAILED", "contact_id": "", "error": str(exc)})
    return pd.DataFrame(results)


CRM_EXPORT_COLUMNS = [
    "audit_id", "first_name", "last_name", "seller_name", "phone", "phone_2", "phone_type", "email",
    "mailing_street", "mailing_city", "mailing_state", "mailing_zip", "property_street", "property_city",
    "property_state", "property_zip", "property_address", "owner_type", "avm", "wholesale_value",
    "mls_status", "mls_list_price", "mls_agent_name", "mls_agent_phone", "mls_agent_email",
    "crm_tags", "sync_action", "sync_reason",
]


def crm_export(queue: pd.DataFrame) -> pd.DataFrame:
    return queue[[column for column in CRM_EXPORT_COLUMNS if column in queue.columns]].copy()
