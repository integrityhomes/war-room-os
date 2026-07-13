from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class LeadTraceVerification:
    verified: bool
    screened_rows: int
    paired_phone_groups: int
    reason: str


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _clean(value).lower())


def verify_paid_leadtrace(df: pd.DataFrame) -> LeadTraceVerification:
    """Verify that an XLeads export contains evidence of completed paid LeadTrace.

    Ordinary XLeads property exports may already contain phone/email fields. Those
    fields alone are not proof that paid LeadTrace ran. Verification requires at
    least one XLeads phone column with its matching DNC and Litigator columns and
    at least one row where the phone and both screening results are populated.
    """
    if df.empty:
        return LeadTraceVerification(False, 0, 0, "The file has no rows.")

    lookup = {_header(column): str(column) for column in df.columns}
    groups: list[tuple[str, str, str]] = []

    for column in df.columns:
        normalized = _header(column)
        if not re.fullmatch(r"contact\d+phone\d+", normalized):
            continue
        dnc_column = lookup.get(f"{normalized}dnc")
        litigator_column = lookup.get(f"{normalized}litigator")
        if dnc_column and litigator_column:
            groups.append((str(column), dnc_column, litigator_column))

    if not groups:
        return LeadTraceVerification(
            False,
            0,
            0,
            "No phone column has both matching DNC and Litigator result columns.",
        )

    screened_mask = pd.Series(False, index=df.index, dtype="bool")
    for phone_column, dnc_column, litigator_column in groups:
        phone_present = df[phone_column].map(_clean).ne("")
        dnc_present = df[dnc_column].map(_clean).ne("")
        litigator_present = df[litigator_column].map(_clean).ne("")
        screened_mask = screened_mask | (phone_present & dnc_present & litigator_present)

    screened_rows = int(screened_mask.sum())
    if screened_rows == 0:
        return LeadTraceVerification(
            False,
            0,
            len(groups),
            "DNC and Litigator columns exist, but no phone row has populated screening results.",
        )

    return LeadTraceVerification(
        True,
        screened_rows,
        len(groups),
        "Paid LeadTrace evidence found: paired phone, DNC, and Litigator results are populated.",
    )
