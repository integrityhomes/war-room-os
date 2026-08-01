"""Build campaign-ready email files for XLeads records that are not callable."""
from __future__ import annotations

from typing import Iterable

import pandas as pd


CAMPAIGN_EMAIL_COLUMNS = (
    "email",
    "email_2",
    "email_3",
)


def _clean(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "null", "<na>"} else text


def _tags(row: pd.Series, lane_tag: str) -> str:
    existing = [item.strip() for item in _clean(row.get("xleads_tags")).split(",") if item.strip()]
    extra = [lane_tag, "email-campaign-ready", "do-not-call-by-phone"]
    return ",".join(dict.fromkeys(existing + extra))


def _expand_email_rows(queue: pd.DataFrame, mask: pd.Series, lane_tag: str) -> pd.DataFrame:
    records: list[dict[str, str]] = []
    selected = queue.loc[mask].copy()

    for _, row in selected.iterrows():
        seen: set[str] = set()
        for email_column in CAMPAIGN_EMAIL_COLUMNS:
            email = _clean(row.get(email_column)).lower()
            if not email or email in seen:
                continue
            seen.add(email)
            records.append(
                {
                    "FirstName": _clean(row.get("first_name")),
                    "LastName": _clean(row.get("last_name")),
                    "Email": email,
                    "PropertyAddress": _clean(row.get("property_street")),
                    "PropertyCity": _clean(row.get("property_city")),
                    "PropertyState": _clean(row.get("property_state")),
                    "PropertyPostalCode": _clean(row.get("property_zip")),
                    "RecipientAddress": _clean(row.get("mailing_street")),
                    "RecipientCity": _clean(row.get("mailing_city")),
                    "RecipientState": _clean(row.get("mailing_state")),
                    "RecipientPostalCode": _clean(row.get("mailing_zip")),
                    "Tags": _tags(row, lane_tag),
                    "LeadSource": "XLeads LeadTrace - Cannot Call Email",
                    "PhoneCampaignStatus": _clean(row.get("phone_action")),
                    "EmailCampaignStatus": _clean(row.get("email_action")),
                    "AuditID": _clean(row.get("audit_id")),
                }
            )

    columns = [
        "FirstName",
        "LastName",
        "Email",
        "PropertyAddress",
        "PropertyCity",
        "PropertyState",
        "PropertyPostalCode",
        "RecipientAddress",
        "RecipientCity",
        "RecipientState",
        "RecipientPostalCode",
        "Tags",
        "LeadSource",
        "PhoneCampaignStatus",
        "EmailCampaignStatus",
        "AuditID",
    ]
    if not records:
        return pd.DataFrame(columns=columns)

    output = pd.DataFrame(records, columns=columns)
    return output.drop_duplicates(subset=["Email", "PropertyAddress", "PropertyPostalCode"], keep="first").reset_index(drop=True)


def cannot_call_email_export(queue: pd.DataFrame) -> pd.DataFrame:
    """Usable emails where no phone is approved for text or voice."""
    mask = queue["email_ready"].astype(bool) & ~queue["phone_ready"].astype(bool)
    return _expand_email_rows(queue, mask, "cannot-call-email")


def dnc_email_campaign_export(queue: pd.DataFrame) -> pd.DataFrame:
    """Usable emails where every usable phone is specifically held for DNC/litigator/internal opt-out."""
    mask = queue["email_ready"].astype(bool) & queue["phone_action"].eq("DNC_PHONE_HOLD")
    return _expand_email_rows(queue, mask, "dnc-email-campaign-ready")


def email_suppression_audit(queue: pd.DataFrame) -> pd.DataFrame:
    columns: Iterable[str] = (
        "audit_id",
        "first_name",
        "last_name",
        "seller_name",
        "email",
        "email_2",
        "email_3",
        "property_address",
        "phone_action",
        "email_action",
        "email_reason",
        "xleads_tags",
    )
    available = [column for column in columns if column in queue.columns]
    return queue.loc[queue["email_action"].ne("READY_FOR_XLEADS_EMAIL"), available].copy()
