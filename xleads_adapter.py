"""Adapter for real XLeads exports.

Delegates seller-reply intelligence to lead_intelligence.py and provides
compliance-safe contact selection plus value-aware raw-property scoring.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

import pandas as pd

import lead_intelligence as base

DEFAULT_TARGET_STATES = base.DEFAULT_TARGET_STATES
clean_text = base.clean_text
run_greatness_test = base.run_greatness_test
score_reply_lead = base.score_reply_lead

TRUE_VALUES = {"1", "true", "yes", "y", "checked", "x"}
FALSE_VALUES = {"0", "false", "no", "n", "unchecked"}


def norm(value: Any) -> str:
    return clean_text(value).strip().lower()


def truthy(value: Any) -> bool:
    return norm(value) in TRUE_VALUES


def falsey(value: Any) -> bool:
    return norm(value) in FALSE_VALUES


def money(value: Any) -> float | None:
    text = re.sub(r"[^0-9.\-]", "", clean_text(value))
    if not text or text in {"-", "."}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def clean_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", clean_text(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def select_contact(row: Mapping[str, Any]) -> dict[str, Any]:
    """Select the safest usable XLeads phone without hiding other opportunities."""
    candidates: list[dict[str, Any]] = []
    for index in range(1, 4):
        phone = clean_phone(row.get(f"Contact1Phone_{index}", ""))
        if not phone:
            continue
        dnc_raw = row.get(f"Contact1Phone_{index}_DNC", "")
        litigator_raw = row.get(f"Contact1Phone_{index}_Litigator", "")
        candidates.append({
            "index": index,
            "phone": phone,
            "type": clean_text(row.get(f"Contact1Phone_{index}_Type", "")),
            "dnc": truthy(dnc_raw),
            "litigator": truthy(litigator_raw),
            "dnc_known_clear": falsey(dnc_raw),
            "dnc_unknown": not truthy(dnc_raw) and not falsey(dnc_raw),
            "email": clean_text(row.get(f"Contact1Email_{index}", "")),
        })

    explicitly_clear = [item for item in candidates if item["dnc_known_clear"] and not item["litigator"]]
    unknown_status = [item for item in candidates if item["dnc_unknown"] and not item["litigator"]]
    blocked = [item for item in candidates if item["dnc"] or item["litigator"]]

    if explicitly_clear:
        selected = explicitly_clear[0]
        status = "CLEAR"
    elif unknown_status:
        selected = unknown_status[0]
        status = "UNKNOWN_REVIEW"
    else:
        selected = None
        status = "BLOCKED" if candidates else "NO_PHONE"

    return {
        "selected_phone": selected["phone"] if selected else "",
        "selected_phone_type": selected["type"] if selected else "",
        "selected_phone_index": selected["index"] if selected else None,
        "selected_email": selected["email"] if selected and selected["email"] else clean_text(row.get("Contact1Email_1", "")),
        "contact_compliance_status": status,
        "available_phone_count": len(candidates),
        "clear_phone_count": len(explicitly_clear),
        "unknown_phone_count": len(unknown_status),
        "blocked_phone_count": len(blocked),
        "has_mixed_phone_compliance": bool(blocked and (explicitly_clear or unknown_status)),
    }


def signal(row: Mapping[str, Any], name: str) -> bool:
    """Read XLeads 0/1 fields by value, never by column-name presence."""
    return truthy(row.get(name, ""))


def raw_result(**overrides: Any) -> dict[str, Any]:
    result = base.base_result(
        lead_status="Raw Lead Review",
        lead_lane="Review",
        call_lane="Do Not Call Yet",
        call_priority_rank=90,
        call_deadline="Wait for seller engagement",
        must_call=False,
        human_review_required=True,
        confidence=0.9,
        recommended_next_step="Review before marketing.",
        rei_blackbook_tag="XLEADS_RAW_REVIEW",
        rei_blackbook_tags="XLEADS_RAW_REVIEW",
        rei_blackbook_workflow="Raw Lead Review",
        xleads_action="DATA_REVIEW",
    )
    result.update(overrides)
    return result


def score_raw_lead(row: Mapping[str, Any], target_states: Sequence[str] = DEFAULT_TARGET_STATES) -> dict[str, Any]:
    contact = select_contact(row)
    property_address = clean_text(row.get("property_address", row.get("PropertyAddress", "")))
    owner_name = clean_text(row.get("seller_name", "")) or " ".join(filter(None, [clean_text(row.get("FirstName", "")), clean_text(row.get("LastName", ""))])).strip()
    state = clean_text(row.get("property_state", row.get("PropertyState", ""))).upper()
    targets = {item.strip().upper() for item in target_states if item.strip()}
    in_market = not targets or not state or state in targets

    reasons: list[str] = []
    risks: list[str] = []
    score = 0

    if property_address:
        score += 8
        reasons.append("property address present")
    if owner_name:
        score += 5
        reasons.append("owner identified")
    if contact["selected_phone"]:
        score += 12
        reasons.append("usable phone available")
    if contact["selected_email"]:
        score += 3
        reasons.append("email available")
    if in_market:
        score += 5
        reasons.append("inside target market")
    else:
        risks.append("OUTSIDE_TARGET_MARKET")

    weighted_signals = [
        ("PreForeclosure", 22, "pre-foreclosure"),
        ("Foreclosures", 20, "foreclosure record"),
        ("ZombieProperty", 20, "zombie property"),
        ("DeceasedProbate", 18, "deceased/probate"),
        ("DelinquentTaxActivity", 17, "delinquent tax activity"),
        ("Vacancy", 15, "vacant property"),
        ("BoredInvestor", 13, "bored investor"),
        ("PotentiallyInherited", 13, "potential inheritance"),
        ("HighEquity", 10, "high equity"),
        ("FreeAndClear", 9, "free and clear"),
        ("LongTermOwner", 6, "long-term owner"),
        ("ActiveInvestorOwned", 5, "investor owned"),
    ]
    distress_count = 0
    for field, points, label in weighted_signals:
        if signal(row, field):
            score += points
            reasons.append(label)
            if points >= 13:
                distress_count += 1

    lien_count = money(row.get("NumberOfLiens", "")) or 0
    total_liens = money(row.get("TotalLiens", "")) or 0
    if lien_count > 0:
        score += min(12, 5 + int(lien_count) * 2)
        reasons.append(f"{int(lien_count)} lien(s)")
    if total_liens > 0:
        reasons.append("recorded lien balance")

    mls_status = norm(row.get("MLS_Curr_Status", ""))
    list_price = money(row.get("MLS_Curr_ListPrice", ""))
    wholesale_value = money(row.get("WholesaleValue", ""))
    avm = money(row.get("AVM", ""))
    market_value = money(row.get("MarketValue", ""))

    if mls_status == "active":
        reasons.append("active MLS listing")
        score += 2
    elif mls_status in {"pending", "under contract"}:
        risks.append("MLS_PENDING")
        score -= 8
    elif mls_status == "sold":
        risks.append("MLS_SOLD")
        score -= 20

    reference_value = wholesale_value or avm or market_value
    if list_price and reference_value and reference_value > 0:
        ratio = list_price / reference_value
        if ratio <= 0.75:
            score += 12
            reasons.append("list price materially below estimated value")
        elif ratio <= 1.0:
            score += 6
            reasons.append("list price at or below estimated value")
        elif ratio >= 1.5:
            risks.append("HIGH_LIST_PRICE_TO_VALUE")
            score -= 5

    if distress_count >= 2:
        score += 7
        reasons.append("stacked distress signals")
    if distress_count >= 3:
        score += 5

    if contact["has_mixed_phone_compliance"]:
        risks.append("MIXED_PHONE_COMPLIANCE")
    if contact["contact_compliance_status"] == "UNKNOWN_REVIEW":
        risks.append("DNC_STATUS_UNKNOWN")
    elif contact["contact_compliance_status"] == "BLOCKED":
        risks.append("ALL_PHONES_BLOCKED")
    elif contact["contact_compliance_status"] == "NO_PHONE":
        risks.append("NO_PHONE")

    score = max(0, min(100, score))

    if contact["contact_compliance_status"] == "BLOCKED":
        status = "Compliance Hold — All Phones Blocked"
        lane = "Compliance Review"
        action = "DO_NOT_CONTACT"
        tag = "XLEADS_ALL_PHONES_BLOCKED"
        review = True
        next_step = "Do not call or text. Keep the property record for research only."
    elif contact["contact_compliance_status"] == "NO_PHONE":
        status = "Needs Phone / Skip Trace"
        lane = "Needs Data"
        action = "SKIP_TRACE"
        tag = "XLEADS_NEEDS_SKIPTRACE"
        review = False
        next_step = "Find a compliant contact method before outreach."
    elif contact["contact_compliance_status"] == "UNKNOWN_REVIEW":
        status = "Compliance Review — DNC Unknown"
        lane = "Compliance Review"
        action = "VERIFY_DNC_BEFORE_CAMPAIGN"
        tag = "XLEADS_DNC_UNKNOWN"
        review = True
        next_step = "Verify DNC status before adding this contact to an outreach campaign."
    elif not in_market:
        status = "Outside Target Market"
        lane = "Review"
        action = "MARKET_REVIEW"
        tag = "XLEADS_OUTSIDE_MARKET"
        review = True
        next_step = "Confirm the market is approved before outreach."
    elif "MLS_SOLD" in risks:
        status = "Property Sold Review"
        lane = "Review"
        action = "PROPERTY_STATUS_REVIEW"
        tag = "XLEADS_MLS_SOLD"
        review = True
        next_step = "Verify current ownership and property status before outreach."
    elif score >= 62:
        status = "Priority Campaign Lead"
        lane = "Raw Lead Prioritizer"
        action = "PRIORITY_TEXT_CAMPAIGN"
        tag = "XLEADS_PRIORITY_RAW_LEAD"
        review = False
        next_step = "Send through the approved XLeads campaign. Call only after seller engagement or permission."
    elif score >= 38:
        status = "Ready for Campaign"
        lane = "Raw Lead Prioritizer"
        action = "TEXT_CAMPAIGN"
        tag = "XLEADS_READY_FOR_TEXT"
        review = False
        next_step = "Include in the approved XLeads campaign. Call only after seller engagement or permission."
    else:
        status = "Raw Lead Review"
        lane = "Review"
        action = "DATA_REVIEW"
        tag = "XLEADS_RAW_REVIEW"
        review = True
        next_step = "Review property data before marketing."

    result = raw_result(
        lead_status=status,
        lead_score=score,
        opportunity_score_10=round(score / 10, 1),
        lead_lane=lane,
        human_review_required=review,
        motivation=", ".join(reasons),
        score_explanation="Raw score uses actual XLeads 0/1 values, property distress, value gap, contact quality, and compliance.",
        recommended_next_step=next_step,
        risk_flags=", ".join(risks),
        reason_codes=", ".join(reasons),
        rei_blackbook_tag=tag,
        rei_blackbook_tags=tag,
        rei_blackbook_workflow=status,
        xleads_action=action,
    )
    result.update(contact)
    result["phone"] = contact["selected_phone"]
    result["email"] = contact["selected_email"]
    return result


def score_dataframe(df: pd.DataFrame, file_mode: str, target_states: Sequence[str] = DEFAULT_TARGET_STATES) -> pd.DataFrame:
    if file_mode == "Seller Replies":
        return base.score_dataframe(df, file_mode, target_states)

    results = [score_raw_lead(row.to_dict(), target_states) for _, row in df.iterrows()]
    out = pd.concat([df.reset_index(drop=True), pd.DataFrame(results)], axis=1)
    out["phone"] = out["selected_phone"].fillna("")
    out["email"] = out["selected_email"].fillna("")
    out["clean_phone"] = out["selected_phone"].fillna("")
    out["opt_out_detected"] = out["contact_compliance_status"].eq("BLOCKED")
    out["wrong_number_detected"] = False
    out["seller_requested_call"] = False
    out["inside_calling_hours"] = True
    out["ai_call_allowed"] = False
    out["human_call_task_allowed"] = False

    address = out.get("property_address", out.get("PropertyAddress", pd.Series([""] * len(out)))).astype(str)
    out["address_key"] = address.str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    out["duplicate_key"] = out["address_key"]
    sizes = out["duplicate_key"].map(out["duplicate_key"].value_counts()).fillna(1).astype(int)
    out["duplicate_group_size"] = sizes
    out["duplicate_flag"] = sizes.gt(1)
    out["duplicate_primary"] = True
    for _, indexes in out[out["duplicate_key"].ne("")].groupby("duplicate_key").groups.items():
        if len(indexes) > 1:
            best = out.loc[indexes, "lead_score"].astype(float).idxmax()
            for index in indexes:
                if index != best:
                    out.at[index, "duplicate_primary"] = False
                    out.at[index, "lead_status"] = "Duplicate / Suppress"
                    out.at[index, "lead_lane"] = "Duplicate / Suppress"
                    out.at[index, "xleads_action"] = "SUPPRESS_DUPLICATE"

    out["summary_note"] = out.apply(
        lambda row: (
            f"War Room OS | Raw XLeads | {row.get('lead_status', '')} | "
            f"Score {row.get('lead_score', 0)}/100 | Phone compliance: {row.get('contact_compliance_status', '')} | "
            f"Why: {row.get('motivation', '')} | Risks: {row.get('risk_flags', '')}"
        ),
        axis=1,
    )
    return out.sort_values(["lead_score", "confidence"], ascending=[False, False], kind="stable").reset_index(drop=True)
