"""Explainable, testable intelligence layer for the XLeads lead-manager bot."""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence
import pandas as pd

DEFAULT_TARGET_STATES = ("IL", "MO", "IN", "MI", "OH", "AL", "VA")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(value).lower().replace("’", "'")).strip()


def clean_phone(value: Any) -> str:
    digits = re.sub(r"\D", "", clean_text(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def address_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", norm(value))


def has(text: str, phrases: Iterable[str]) -> bool:
    for phrase in phrases:
        if re.fullmatch(r"[a-z0-9']+", phrase):
            if re.search(rf"\b{re.escape(phrase)}\b", text):
                return True
        elif phrase in text:
            return True
    return False


OPT_OUT = [
    r"^\s*stop\s*[.!]*$", r"\b(remove me|unsubscribe|take me off|leave me alone)\b",
    r"\b(do not|don't|dont)\s+(contact|text|message)\s+me\b",
    r"\b(stop|quit)\s+(texting|messaging|contacting)\s+me\b",
]
CALL_RESTRICT = [r"\b(no calls?|text only|only text|do not call|don't call|dont call)\b"]
WRONG = [r"\bwrong number\b", r"\bwrong person\b", r"\byou have the wrong (number|person)\b"]
CALL = ("call me", "give me a call", "you can call", "please call", "call now", "call after", "call around", "call anytime")
OFFER = ("make me an offer", "what is your offer", "what's your offer", "send offer", "what will you pay", "how much will you pay", "what are you offering", "how much", "offer?")
SELL = ("i would sell", "i will sell", "i'll sell", "ready to sell", "want to sell", "need to sell", "interested in selling", "open to selling", "willing to sell")
CONDITIONAL = ("maybe", "possibly", "depends", "right price", "might sell", "would consider", "could sell", "open to an offer", "not sure")
INFO = ("who is this", "what company", "send me information", "send information", "tell me more", "how does this work")
REJECT = ("not interested", "never selling", "not for sale", "i am not selling", "i'm not selling", "do not want to sell", "don't want to sell")
SOLD = ("already sold", "it sold", "property sold", "sold it", "sold already", "under contract")
NON_OWNER = ("not the owner", "i don't own", "i dont own", "not my property", "not my house", "don't own it anymore", "dont own it anymore")
OTHER_PROPERTY = ("another house", "another property", "other house", "other property", "other properties", "two others", "more properties")
POSITIVE_SHORT = {"yes", "yes.", "yeah", "yep", "sure", "ok", "okay", "possibly", "maybe"}
NEGATIVE_SHORT = {"no", "nope", "nah", "never"}

MOTIVATION = [
    (25, "foreclosure pressure", ("foreclosure", "auction date", "preforeclosure", "behind on mortgage")),
    (22, "inherited/probate", ("inherited", "inheritance", "probate", "estate property")),
    (22, "code/condemnation", ("code violation", "condemned", "city fines")),
    (20, "tax pressure", ("behind on taxes", "delinquent taxes", "tax sale", "tax lien", "back taxes")),
    (18, "vacant property", ("vacant", "empty house", "unoccupied")),
    (18, "landlord/tenant problem", ("tired landlord", "bad tenant", "tenant destroyed", "evict", "eviction", "nonpaying tenant")),
    (18, "repair burden", ("can't afford repairs", "cant afford repairs", "too expensive to fix", "money pit")),
    (15, "life event", ("divorce", "relocating", "moving out of state", "job transfer", "nursing home")),
    (14, "seller fatigue", ("tired of it", "done with it", "need it gone", "get rid of it", "don't want to deal", "dont want to deal")),
]
CONDITION = [
    (10, "severe damage", ("fire damage", "foundation", "collapsed", "condemned", "flood damage")),
    (9, "major systems", ("roof", "mold", "no hvac", "hvac", "electrical", "plumbing", "septic", "furnace")),
    (8, "heavy repairs", ("needs a lot of work", "needs major repairs", "gut job", "full rehab", "tenant destroyed", "needs work")),
    (5, "cleanup/outdated", ("cleanout", "hoarder", "outdated", "fixer", "as-is", "as is", "repairs")),
]
URGENT = ("asap", "right away", "immediately", "this week", "today", "tomorrow", "need it gone", "as soon as possible", "before foreclosure", "before auction")
SOON = ("this month", "within 30 days", "next 30 days", "in a few weeks", "couple weeks", "soon")
MEDIUM = ("next month", "30 to 90 days", "30-90 days", "within 90 days", "in a couple months", "few months")
LATER = ("later", "not right now", "this winter", "this summer", "this fall", "this spring", "next year", "down the road", "no rush")
FLEXIBLE = ("negotiable", "flexible", "or best offer", "obo", "around", "roughly", "make an offer", "open to an offer")
FIRM = ("firm", "won't take less", "wont take less", "not taking less", "bottom dollar", "zillow says", "full market value", "retail")


def detect_opt_out(value: Any) -> bool:
    text = norm(value)
    return any(re.search(pattern, text) for pattern in OPT_OUT)


def detect_call_restriction(value: Any) -> bool:
    text = norm(value)
    return any(re.search(pattern, text) for pattern in CALL_RESTRICT)


def detect_wrong_number(value: Any) -> bool:
    text = norm(value)
    return any(re.search(pattern, text) for pattern in WRONG)


def detect_call_permission(value: Any) -> bool:
    text = norm(value)
    return has(text, CALL) and not detect_call_restriction(text)


def extract_prices(value: Any) -> list[int]:
    text, values = norm(value), []
    for pattern in (r"\$\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([km])?", r"\b(\d{1,3}(?:\.\d+)?)\s*k\b", r"\b(\d{1,3}(?:,\d{3})+)\b"):
        for match in re.finditer(pattern, text):
            amount = float(match.group(1).replace(",", ""))
            suffix = match.group(2) if match.lastindex and match.lastindex >= 2 else None
            if suffix == "k" or " k" in match.group(0):
                amount *= 1000
            if suffix == "m":
                amount *= 1_000_000
            if 1_000 <= amount <= 10_000_000:
                values.append(int(amount))
    if re.search(r"\b(take|want|asking|sell for|price|offer|need|get)\b", text):
        values += [int(m.group()) for m in re.finditer(r"\b\d{4,7}\b", text) if 1_000 <= int(m.group()) <= 10_000_000]
    return sorted(set(values))


def combined_text(row: Mapping[str, Any]) -> str:
    fields = ("seller_message", "call_transcript", "call_summary", "call_disposition", "ai_summary", "motivation_detail", "timeline_detail", "condition_detail", "occupancy_detail", "price_detail", "notes")
    return norm(" | ".join(clean_text(row.get(field, "")) for field in fields if clean_text(row.get(field, ""))))


def best_group(text: str, groups) -> tuple[int, list[str]]:
    matches = [(points, label) for points, label, phrases in groups if has(text, phrases)]
    return max((points for points, _ in matches), default=0), [label for _, label in matches]


def base_result(**overrides) -> dict[str, Any]:
    result = dict(
        lead_status="Needs Review", lead_score=0, opportunity_score_10=0.0,
        lead_lane="Human Review", call_lane="Human Review", call_priority_rank=3,
        call_deadline="Review before end of day", must_call=False,
        human_review_required=True, confidence=0.55, motivation="",
        score_explanation="", recommended_next_step="Human review required.",
        recommended_next_question="", missing_information="", risk_flags="",
        reason_codes="", rei_blackbook_tag="AI_HUMAN_REVIEW",
        rei_blackbook_tags="AI_HUMAN_REVIEW", rei_blackbook_workflow="Human Review Required",
        xleads_action="HUMAN_REVIEW", call_permission="No",
        asking_price_extracted=None, timeline_bucket="Unknown",
        other_property_opportunity=False, price_expectation_review=False,
    )
    result.update(overrides)
    return result


def blocked(status: str, reason: str, tag: str) -> dict[str, Any]:
    return base_result(
        lead_status=status, lead_lane="Blocked", call_lane="Do Not Contact",
        call_priority_rank=99, call_deadline="Do not contact", human_review_required=False,
        confidence=.99, motivation=reason, score_explanation=reason,
        recommended_next_step=reason, risk_flags="COMPLIANCE_BLOCK",
        reason_codes="COMPLIANCE_BLOCK", rei_blackbook_tag=tag,
        rei_blackbook_tags=tag, rei_blackbook_workflow=status,
        xleads_action="STOP_ALL_AUTOMATION",
    )


def score_reply_lead(row: Mapping[str, Any]) -> dict[str, Any]:
    text, message = combined_text(row), norm(row.get("seller_message", ""))
    if detect_opt_out(text):
        return blocked("DNC / Opt-Out", "Seller opted out. Compliance overrides every opportunity signal.", "AI_DNC")
    if detect_wrong_number(text):
        return blocked("Wrong Number", "Recipient clearly identified a wrong number or wrong person.", "BAD_NUMBER")

    call_permission = detect_call_permission(text)
    call_restricted = detect_call_restriction(text)
    offer, explicit, conditional, info = has(text, OFFER), has(text, SELL), has(text, CONDITIONAL), has(text, INFO)
    other, sold, non_owner = has(text, OTHER_PROPERTY), has(text, SOLD), has(text, NON_OWNER)
    prices, firm = extract_prices(text), has(text, FIRM)
    reasons, risks, missing, codes = [], [], [], []

    if call_permission:
        intent, reasons = 25, ["seller requested or approved a call"]
    elif offer:
        intent, reasons = 23, ["seller requested an offer or price"]
    elif explicit:
        intent, reasons = 21, ["seller clearly expressed willingness to sell"]
    elif message in POSITIVE_SHORT:
        intent, reasons = 17, ["short positive seller reply"]
    elif conditional:
        intent, reasons = 15, ["seller expressed conditional interest"]
    elif other:
        intent, reasons = 18, ["seller mentioned another property opportunity"]
    elif info:
        intent, reasons = 8, ["seller requested information"]
    else:
        intent = 0

    motivation, motivation_labels = best_group(text, MOTIVATION)
    motivation = min(25, motivation + (4 if len(motivation_labels) >= 2 else 0))
    if motivation_labels:
        reasons.append("motivation: " + ", ".join(motivation_labels))

    if has(text, URGENT):
        timeline, timeline_bucket = 20, "Now / 7 days"
        reasons.append("urgent selling timeline")
    elif has(text, SOON):
        timeline, timeline_bucket = 16, "Within 30 days"
        reasons.append("near-term timeline")
    elif has(text, MEDIUM):
        timeline, timeline_bucket = 11, "30-90 days"
        reasons.append("30-90 day timeline")
    elif has(text, LATER):
        timeline, timeline_bucket = 5, "Later / nurture"
        reasons.append("later timeline")
    else:
        timeline, timeline_bucket = 0, "Unknown"
        missing.append("selling timeline")

    if prices:
        price = 13 if has(text, FLEXIBLE) else 11
        reasons.append("seller supplied a price")
    elif offer:
        price = 10
        reasons.append("seller invited an offer")
    elif conditional and "price" in text:
        price = 7
        reasons.append("price is the decision point")
    else:
        price = 0
        missing.append("asking price or price flexibility")

    condition, condition_labels = best_group(text, CONDITION)
    if condition_labels:
        reasons.append("condition: " + ", ".join(condition_labels))
    else:
        missing.append("property condition")

    words = len(re.findall(r"\b\w+\b", text))
    detail = len(prices) + len(motivation_labels) + len(condition_labels)
    engagement = 5 if words >= 25 or detail >= 3 else 4 if words >= 10 or "?" in clean_text(row.get("seller_message", "")) or detail else 2 if words >= 2 else 1 if words else 0
    score = max(0, min(100, intent + motivation + timeline + price + condition + engagement))

    if firm:
        risks.append("PRICE_EXPECTATION_REVIEW")
    if non_owner:
        risks.append("OWNERSHIP_VERIFY")
    if sold:
        risks.append("PROPERTY_SOLD")
    if other:
        risks.append("OTHER_PROPERTY_OPPORTUNITY")
    if call_restricted:
        risks += ["NO_CALLS", "TEXT_ONLY"]

    clear_reject = message in NEGATIVE_SHORT or (has(message, REJECT) and not any(marker in message for marker in ("but", "unless", "another", "other", "right price", "offer")))
    if clear_reject and not other:
        return base_result(
            lead_status="Not Interested", lead_lane="Closed", call_lane="Closed / No Call",
            call_priority_rank=98, call_deadline="No call", human_review_required=False,
            confidence=.96, motivation="Clear rejection with no alternate opportunity.",
            score_explanation="Clear rejection.", recommended_next_step="Stop active follow-up.",
            risk_flags="CLEAR_REJECTION", reason_codes="CLEAR_REJECTION",
            rei_blackbook_tag="AI_NOT_INTERESTED", rei_blackbook_tags="AI_NOT_INTERESTED",
            rei_blackbook_workflow="Closed Not Interested", xleads_action="STOP_ACTIVE_FOLLOW_UP",
            asking_price_extracted=min(prices) if prices else None,
            timeline_bucket=timeline_bucket, price_expectation_review=firm,
        )
    if sold and not other:
        return base_result(
            lead_status="Property Sold / Referral Check", lead_score=max(score, 20),
            opportunity_score_10=round(max(score, 20)/10, 1), lead_lane="Follow-Up Queue",
            call_lane="Keep Qualifying", call_priority_rank=4,
            call_deadline="Text today; call only with permission", human_review_required=False,
            confidence=.9, motivation="Property sold; recover value with an other-property/referral question.",
            score_explanation="Sold property referral check.",
            recommended_next_step="Send one concise other-property/referral question.",
            recommended_next_question="Do you have another property you would consider selling, or know someone who does?",
            missing_information="other property or referral opportunity", risk_flags="PROPERTY_SOLD",
            reason_codes="PROPERTY_SOLD, REFERRAL_CHECK", rei_blackbook_tag="AI_SOLD_REFERRAL_CHECK",
            rei_blackbook_tags="AI_SOLD_REFERRAL_CHECK, FOLLOW_UP_BOT_START",
            rei_blackbook_workflow="Sold Property Referral Check", xleads_action="TEXT_NEXT_QUESTION",
            call_permission="Yes" if call_permission else "No",
            asking_price_extracted=min(prices) if prices else None, timeline_bucket=timeline_bucket,
            price_expectation_review=firm,
        )

    for condition_met, code in ((call_permission,"CALL_REQUESTED"),(offer,"OFFER_REQUESTED"),(bool(prices),"PRICE_GIVEN"),(motivation>0,"MOTIVATION_FOUND"),(condition>0,"CONDITION_FOUND"),(conditional or message in POSITIVE_SHORT,"POSITIVE_OR_CONDITIONAL_REPLY"),(other,"OTHER_PROPERTY_OPPORTUNITY")):
        if condition_met:
            codes.append(code)
    strong = sum(value > 0 for value in (intent, motivation, timeline, price, condition)) >= 3
    urgent = timeline == 20

    if call_permission:
        lane, rank, deadline = "Call Now", 1, "Within 5 minutes"
    elif urgent and motivation >= 18:
        lane, rank, deadline = "Call Now", 1, "Within 15 minutes"
    elif score >= 50 and strong and motivation >= 18 and (prices or condition):
        lane, rank, deadline = "Call Now", 1, "Within 15 minutes"
    elif urgent:
        lane, rank, deadline = "Call Today", 2, "Within 2 hours"
    elif timeline_bucket == "Later / nurture" and not (offer or prices or motivation >= 18):
        lane, rank, deadline = "Scheduled Follow-Up", 5, "Schedule for seller timeframe"
    elif score >= 62 or codes:
        lane, rank, deadline = "Call Today", 2, "Within 2 hours"
    elif score >= 20 or info:
        lane, rank, deadline = "Keep Qualifying", 4, "Text next question today"
    else:
        lane, rank, deadline = "Human Review", 3, "Review before end of day"

    if call_restricted and lane in {"Call Now", "Call Today"}:
        lane, rank, deadline = "Keep Qualifying", 4, "Text only today"
    if non_owner and other:
        lane, rank, deadline = ("Keep Qualifying",4,"Text only today") if call_restricted else ("Call Today",2,"Within 2 hours")

    must_call = lane in {"Call Now", "Call Today"}
    review = lane == "Human Review" or (firm and not call_permission and score < 55)
    if lane == "Call Now":
        status, lead_lane, tag, workflow, action = "Hot A Lead", "Must Call Queue", "AI_HOT_LEAD", "Immediate Human Call", "HUMAN_CALL_NOW"
    elif lane == "Call Today":
        status, lead_lane, tag, workflow, action = ("Hot A Lead" if score >= 72 else "Warm B Lead"), "Must Call Queue", ("AI_HOT_LEAD" if score >= 72 else "AI_WARM_LEAD"), "Same Day Human Call", "HUMAN_CALL_TODAY"
    elif lane == "Scheduled Follow-Up":
        status, lead_lane, tag, workflow, action = "Nurture C Lead", "Follow-Up Queue", "AI_WARM_LEAD", "Scheduled Seller Follow Up", "SCHEDULE_FOLLOW_UP"
    elif lane == "Keep Qualifying":
        status, lead_lane, tag, workflow, action = ("Warm B Lead" if score >= 30 else "Nurture C Lead"), "Follow-Up Queue", "AI_WARM_LEAD", "AI Text Qualification", "TEXT_NEXT_QUESTION"
    else:
        status, lead_lane, tag, workflow, action = "Needs Review", "Human Review", "AI_HUMAN_REVIEW", "Human Review Required", "HUMAN_REVIEW"

    if non_owner:
        missing.insert(0, "ownership and correct property")
    missing = list(dict.fromkeys(missing))
    if "ownership and correct property" in missing:
        question = "Are you the owner of another property you would consider selling?"
    elif "selling timeline" in missing:
        question = "About how soon would you want to sell if the numbers made sense?"
    elif "asking price or price flexibility" in missing:
        question = "What price did you have in mind, and is there any flexibility?"
    elif "property condition" in missing:
        question = "What repairs or updates does the property need?"
    else:
        question = "What would be the best next step for you?"

    tags = [tag] + (["AI_CALL_READY","HUMAN_TAKEOVER"] if must_call else []) + (["OFFER_NEEDED"] if offer or prices else []) + (["FOLLOW_UP_BOT_START"] if lane in {"Keep Qualifying","Scheduled Follow-Up"} else []) + (["OTHER_PROPERTY_OPPORTUNITY"] if other else []) + (["PRICE_GAP_REVIEW"] if firm else [])
    tags = list(dict.fromkeys(tags))
    confidence = min(.96, .55 + (.18 if call_permission or offer or prices else 0) + (.14 if strong else 0) + (.06 if message in POSITIVE_SHORT or info else 0))
    if review:
        confidence = min(confidence, .69)
    dimensions = f"Intent {intent}/25 | Motivation {motivation}/25 | Timeline {timeline}/20 | Price {price}/15 | Condition {condition}/10 | Engagement {engagement}/5"
    why = "; ".join(reasons) if reasons else "No strong signal confidently identified."
    if codes:
        why += "; safety-net: " + ", ".join(codes)

    return base_result(
        lead_status=status, lead_score=score, opportunity_score_10=round(score/10,1),
        lead_lane=lead_lane, call_lane=lane, call_priority_rank=rank, call_deadline=deadline,
        must_call=must_call, human_review_required=review, confidence=round(confidence,2),
        motivation=why, score_explanation=dimensions,
        recommended_next_step=("Call immediately and use the missing-information question." if lane=="Call Now" else "Call today before lower-priority leads." if lane=="Call Today" else "Continue one-question-at-a-time qualification by text." if lane=="Keep Qualifying" else "Create a dated follow-up task." if lane=="Scheduled Follow-Up" else "Human review required before automation continues."),
        recommended_next_question=question, missing_information=", ".join(missing),
        risk_flags=", ".join(dict.fromkeys(risks)), reason_codes=", ".join(codes),
        rei_blackbook_tag=tag, rei_blackbook_tags=", ".join(tags),
        rei_blackbook_workflow=workflow, xleads_action=action,
        call_permission="Yes" if call_permission else "No",
        asking_price_extracted=min(prices) if prices else None,
        timeline_bucket=timeline_bucket, other_property_opportunity=other,
        price_expectation_review=firm,
    )


def raw_dnc(row: Mapping[str, Any]) -> bool:
    for key, value in row.items():
        if any(token in norm(key) for token in ("dnc","do_not_call","donotcall")) and norm(value) in {"true","yes","1","checked","x","dnc"}:
            return True
    return has(" ".join(norm(value) for value in row.values()), ("do not call","donotcall","dnc","litigator","blacklist"))


def score_raw_lead(row: Mapping[str, Any], target_states: Sequence[str]=DEFAULT_TARGET_STATES) -> dict[str, Any]:
    if raw_dnc(row):
        return blocked("Compliance Hold", "Raw record contains a DNC/litigator/blacklist indicator.", "XLEADS_DNC_REVIEW")
    phone, address, owner, email = clean_phone(row.get("phone")), clean_text(row.get("property_address")), clean_text(row.get("seller_name")), clean_text(row.get("email"))
    state, mail_state = clean_text(row.get("property_state")).upper(), clean_text(row.get("mailing_state")).upper()
    zip_code, mail_zip = clean_text(row.get("property_zip")), clean_text(row.get("mailing_zip"))
    score, reasons, missing, risks = 0, [], [], []
    for present, points, label in ((bool(phone),25,"valid phone"),(bool(address),15,"property address"),(bool(owner),8,"owner name"),(bool(email),4,"email")):
        if present:
            score += points
            reasons.append(label)
        elif label != "email":
            missing.append(label)
    targets = {item.strip().upper() for item in target_states if item.strip()}
    in_market = not targets or not state or state in targets
    if in_market:
        score += 8
        reasons.append("inside configured market")
    else:
        risks.append("OUTSIDE_TARGET_MARKET")
    if zip_code and mail_zip and zip_code != mail_zip:
        score += 10
        reasons.append("absentee owner")
    if state and mail_state and state != mail_state:
        score += 5
        reasons.append("out-of-state owner")
    full = " ".join(f"{norm(k)} {norm(v)}" for k,v in row.items())
    for points,label,phrases in ((15,"vacancy",("vacant","unoccupied")),(15,"tax distress",("tax delinquent","tax lien","tax sale")),(15,"probate/inherited",("probate","inherited","deceased")),(15,"foreclosure",("preforeclosure","foreclosure")),(12,"code distress",("code violation","condemned")),(10,"landlord distress",("tired landlord","eviction","bad tenant")),(8,"high equity",("high equity","free and clear"))):
        if has(full, phrases):
            score += points
            reasons.append(label)
    score = min(100, score)
    if not phone:
        status, action, lead_lane = "Needs Phone / Skip Trace","SKIP_TRACE","Needs Data"
    elif not address:
        status, action, lead_lane = "Needs Property Data","DATA_REVIEW","Needs Data"
    elif not in_market:
        status, action, lead_lane = "Outside Target Market","MARKET_REVIEW","Review"
    elif score >= 70:
        status, action, lead_lane = "Priority Campaign Lead","PRIORITY_TEXT_CAMPAIGN","Raw Lead Prioritizer"
    elif score >= 45:
        status, action, lead_lane = "Ready for Campaign","TEXT_CAMPAIGN","Raw Lead Prioritizer"
    else:
        status, action, lead_lane = "Raw Lead Review","DATA_REVIEW","Review"
    tag = "XLEADS_" + re.sub(r"[^A-Z0-9]+","_",status.upper()).strip("_")
    return base_result(
        lead_status=status, lead_score=score, opportunity_score_10=round(score/10,1),
        lead_lane=lead_lane, call_lane="Do Not Call Yet", call_priority_rank=90,
        call_deadline="Wait for seller engagement", human_review_required=status in {"Outside Target Market","Raw Lead Review"},
        confidence=.9, motivation=", ".join(reasons), score_explanation="Raw-list score measures campaign priority, not seller qualification.",
        recommended_next_step="Send through XLeads campaign; do not call until the seller engages." if action in {"PRIORITY_TEXT_CAMPAIGN","TEXT_CAMPAIGN"} else "Complete data or market review first.",
        missing_information=", ".join(missing), risk_flags=", ".join(risks), reason_codes=", ".join(reasons),
        rei_blackbook_tag=tag, rei_blackbook_tags=tag, rei_blackbook_workflow=status,
        xleads_action=action,
    )


def score_dataframe(df: pd.DataFrame, file_mode: str, target_states: Sequence[str]=DEFAULT_TARGET_STATES) -> pd.DataFrame:
    results = [score_reply_lead(row.to_dict()) if file_mode=="Seller Replies" else score_raw_lead(row.to_dict(),target_states) for _,row in df.iterrows()]
    out = pd.concat([df.reset_index(drop=True),pd.DataFrame(results)],axis=1)
    out["clean_phone"] = out.get("phone",pd.Series([""]*len(out))).apply(clean_phone)
    out["address_key"] = out.get("property_address",pd.Series([""]*len(out))).apply(address_key)
    key = out["clean_phone"].where(out["clean_phone"].ne(""),out["address_key"])
    out["duplicate_key"] = key
    out["duplicate_group_size"] = key.map(key.value_counts()).fillna(1).astype(int)
    out["duplicate_flag"] = out["duplicate_group_size"]>1
    out["duplicate_primary"] = True
    for _, indexes in out[key.ne("")].groupby("duplicate_key").groups.items():
        if len(indexes)>1:
            best = out.loc[indexes,"lead_score"].astype(float).idxmax()
            for index in indexes:
                if index!=best:
                    out.at[index,"duplicate_primary"] = False
                    out.at[index,"must_call"] = False
                    out.at[index,"call_lane"] = "Duplicate / Suppress"
                    out.at[index,"call_priority_rank"] = 97
                    out.at[index,"xleads_action"] = "SUPPRESS_DUPLICATE"
                    out.at[index,"risk_flags"] = ", ".join(filter(None,[clean_text(out.at[index,"risk_flags"]),"DUPLICATE_RECORD"]))
    messages = out.get("seller_message",pd.Series([""]*len(out)))
    out["opt_out_detected"] = messages.apply(detect_opt_out)
    out["wrong_number_detected"] = messages.apply(detect_wrong_number)
    out["seller_requested_call"] = messages.apply(detect_call_permission)
    out["inside_calling_hours"] = True
    out["ai_call_allowed"] = (file_mode=="Seller Replies") & out["seller_requested_call"] & ~out["opt_out_detected"] & ~out["wrong_number_detected"] & out["duplicate_primary"]
    out["human_call_task_allowed"] = (file_mode=="Seller Replies") & out["must_call"].astype(bool) & ~out["opt_out_detected"] & ~out["wrong_number_detected"] & out["duplicate_primary"]
    out["summary_note"] = out.apply(lambda r:f"War Room OS | {file_mode} | {r.get('call_lane','')} | Score {r.get('lead_score',0)}/100 | {r.get('score_explanation','')} | Why: {r.get('motivation','')} | Missing: {r.get('missing_information','')} | Next: {r.get('recommended_next_question','')}",axis=1)
    return out.sort_values(["call_priority_rank","lead_score","confidence"],ascending=[True,False,False],kind="stable").reset_index(drop=True)


def greatness_test_cases():
    return [
        ("Yes","Call Today"),("Maybe, depends on price","Call Today"),("Call me now","Call Now"),
        ("I inherited it. It is vacant, needs a roof, and I would take $30,000.","Call Now"),
        ("I want $100,000","Call Today"),("Not right now, maybe this winter","Scheduled Follow-Up"),
        ("No, but I have another house I might sell","Call Today"),("Already sold","Keep Qualifying"),
        ("Who is this?","Keep Qualifying"),("Stop texting me","Do Not Contact"),("Wrong number","Do Not Contact"),
        ("It needs work","Call Today"),("What will you pay?","Call Today"),("No","Closed / No Call"),
        ("Not interested","Closed / No Call"),("I am behind on taxes and need it gone this week","Call Now"),
        ("The tenant destroyed it and I am tired of dealing with it","Call Today"),("Maybe later","Scheduled Follow-Up"),
        ("I don't own that one anymore but I have two others","Call Today"),("I need $250k firm. Zillow says it is worth $260k","Call Today"),
        ("Can you send me information?","Keep Qualifying"),("Yes, call after 5","Call Now"),
        ("Stop by tomorrow to see it","Call Today"),("No calls, text only. I might sell","Keep Qualifying"),
    ]


def run_greatness_test() -> pd.DataFrame:
    rows=[]
    for message,expected in greatness_test_cases():
        result=score_reply_lead({"seller_message":message})
        actual=result["call_lane"]
        rows.append({"seller_reply":message,"expected_lane":expected,"actual_lane":actual,"score":result["lead_score"],"passed":actual==expected,"why":result["motivation"]})
    return pd.DataFrame(rows)
