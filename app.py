import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st


# =========================
# WAR ROOM OS SETTINGS
# =========================

st.set_page_config(
    page_title="War Room OS",
    page_icon="🏠",
    layout="wide"
)

APP_TITLE = "War Room OS"
MODULE_TITLE = "Seller Lead Command"

DEFAULT_TIMEZONE = "America/Chicago"

HOT_THRESHOLD = 80
WARM_THRESHOLD = 50

ZAPIER_WEBHOOK_URL = st.secrets.get("ZAPIER_WEBHOOK_URL", "")


# =========================
# BASIC HELPERS
# =========================

def clean_phone(phone):
    if pd.isna(phone):
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def detect_opt_out(message):
    message = str(message).lower()
    opt_out_phrases = [
        "stop",
        "remove me",
        "unsubscribe",
        "do not contact",
        "don't contact",
        "dont contact",
        "take me off",
        "quit texting",
        "leave me alone"
    ]
    return any(phrase in message for phrase in opt_out_phrases)


def detect_wrong_number(message):
    message = str(message).lower()
    wrong_number_phrases = [
        "wrong number",
        "not my house",
        "not my property",
        "i don't own",
        "i dont own",
        "not the owner",
        "wrong person"
    ]
    return any(phrase in message for phrase in wrong_number_phrases)


def detect_call_permission(message):
    message = str(message).lower()
    call_phrases = [
        "call me",
        "give me a call",
        "you can call",
        "yes call",
        "call this number",
        "have someone call",
        "please call",
        "call anytime",
        "call now"
    ]
    return any(phrase in message for phrase in call_phrases)


def inside_calling_hours(timezone_name):
    try:
        now = datetime.now(ZoneInfo(timezone_name))
    except Exception:
        now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))

    return 8 <= now.hour < 21


def normalize_columns(df):
    rename_map = {}

    possible_columns = {
        "seller_name": ["seller", "name", "owner", "owner_name", "full_name", "seller_name"],
        "phone": ["phone", "phone_number", "mobile", "number"],
        "email": ["email", "email_address"],
        "property_address": ["property", "address", "property_address", "site_address"],
        "seller_message": ["message", "reply", "seller_reply", "last_message", "sms", "body", "seller_message"],
        "campaign_name": ["campaign", "campaign_name", "list_name"],
        "source": ["source"],
        "seller_timezone": ["timezone", "seller_timezone", "time_zone"]
    }

    lower_cols = {c.lower().strip(): c for c in df.columns}

    for standard, options in possible_columns.items():
        for option in options:
            if option in lower_cols:
                rename_map[lower_cols[option]] = standard
                break

    df = df.rename(columns=rename_map)

    required_columns = [
        "seller_name",
        "phone",
        "email",
        "property_address",
        "seller_message",
        "campaign_name",
        "source",
        "seller_timezone"
    ]

    for col in required_columns:
        if col not in df.columns:
            df[col] = ""

    df["source"] = df["source"].replace("", "XLeads").fillna("XLeads")
    df["seller_timezone"] = df["seller_timezone"].replace("", DEFAULT_TIMEZONE).fillna(DEFAULT_TIMEZONE)

    return df


# =========================
# LEAD SCORING BOT
# =========================

def score_lead(row):
    message = str(row.get("seller_message", "")).lower()

    if detect_opt_out(message):
        return {
            "lead_status": "DNC / Opt-Out",
            "lead_score": 0,
            "motivation": "Seller opted out or asked not to be contacted.",
            "recommended_next_step": "Stop all contact immediately.",
            "recommended_next_question": "",
            "rei_blackbook_tag": "XLEADS_DNC",
            "rei_blackbook_workflow": "Do Not Contact",
            "call_permission": "No"
        }

    if detect_wrong_number(message):
        return {
            "lead_status": "Wrong Number",
            "lead_score": 0,
            "motivation": "Wrong number or seller says they do not own the property.",
            "recommended_next_step": "Mark as wrong number. Do not continue.",
            "recommended_next_question": "",
            "rei_blackbook_tag": "XLEADS_WRONG_NUMBER",
            "rei_blackbook_workflow": "Wrong Number",
            "call_permission": "No"
        }

    score = 0
    reasons = []

    hot_phrases = {
        "make me an offer": 30,
        "what is your offer": 30,
        "how much": 25,
        "what will you pay": 25,
        "i would sell": 25,
        "i will sell": 25,
        "i'll sell": 25,
        "yes i would sell": 30,
        "send offer": 30,
        "call me": 25,
        "give me a call": 25
    }

    motivation_phrases = {
        "vacant": 20,
        "inherited": 20,
        "behind on taxes": 20,
        "taxes": 10,
        "needs work": 15,
        "repairs": 15,
        "tired landlord": 20,
        "tenant": 10,
        "evict": 20,
        "code violations": 20,
        "condemned": 25,
        "asap": 20,
        "quickly": 15,
        "need it gone": 25,
        "divorce": 15,
        "foreclosure": 25
    }

    warm_phrases = {
        "maybe": 15,
        "depends": 20,
        "depends on price": 25,
        "not sure": 10,
        "what company": 10,
        "who is this": 5,
        "not right now": 10,
        "later": 10
    }

    for phrase, points in hot_phrases.items():
        if phrase in message:
            score += points
            reasons.append(phrase)

    for phrase, points in motivation_phrases.items():
        if phrase in message:
            score += points
            reasons.append(phrase)

    for phrase, points in warm_phrases.items():
        if phrase in message:
            score += points
            reasons.append(phrase)

    if detect_call_permission(message):
        score += 20
        reasons.append("seller gave call permission")

    score = min(score, 100)

    if score >= HOT_THRESHOLD:
        status = "Hot A Lead"
        tag = "XLEADS_HOT_SELLER"
        workflow = "Hot Seller Immediate Call"
        next_step = "Push to REI BlackBook and create immediate call task."
    elif score >= WARM_THRESHOLD:
        status = "Warm B Lead"
        tag = "XLEADS_WARM_SELLER"
        workflow = "Warm Seller Follow Up"
        next_step = "Keep qualifying. Ask one question at a time."
    elif score > 0:
        status = "Nurture C Lead"
        tag = "XLEADS_NURTURE"
        workflow = "Long Term Nurture"
        next_step = "Add to follow-up queue."
    else:
        status = "Needs Review"
        tag = "XLEADS_AI_REVIEWED"
        workflow = "Needs Review"
        next_step = "Needs human review."

    if status in ["Hot A Lead", "Warm B Lead"]:
        next_question = "Is the property currently vacant or occupied?"
    elif status == "Nurture C Lead":
        next_question = "Would you consider selling later if the numbers made sense?"
    else:
        next_question = ""

    return {
        "lead_status": status,
        "lead_score": score,
        "motivation": ", ".join(reasons) if reasons else "Not clear yet.",
        "recommended_next_step": next_step,
        "recommended_next_question": next_question,
        "rei_blackbook_tag": tag,
        "rei_blackbook_workflow": workflow,
        "call_permission": "Yes" if detect_call_permission(message) else "No"
    }


def score_dataframe(df):
    scored_rows = []

    for _, row in df.iterrows():
        result = score_lead(row)
        scored_rows.append(result)

    scored_df = pd.concat(
        [df.reset_index(drop=True), pd.DataFrame(scored_rows).reset_index(drop=True)],
        axis=1
    )

    scored_df["clean_phone"] = scored_df["phone"].apply(clean_phone)
    scored_df["opt_out_detected"] = scored_df["seller_message"].apply(detect_opt_out)
    scored_df["wrong_number_detected"] = scored_df["seller_message"].apply(detect_wrong_number)
    scored_df["seller_requested_call"] = scored_df["seller_message"].apply(detect_call_permission)
    scored_df["inside_calling_hours"] = scored_df["seller_timezone"].apply(inside_calling_hours)

    scored_df["ai_call_allowed"] = (
        (scored_df["call_permission"] == "Yes") &
        (scored_df["opt_out_detected"] == False) &
        (scored_df["wrong_number_detected"] == False) &
        (scored_df["inside_calling_hours"] == True)
    )

    scored_df["human_call_task_allowed"] = (
        (scored_df["lead_status"].isin(["Hot A Lead", "Warm B Lead"])) &
        (scored_df["opt_out_detected"] == False) &
        (scored_df["wrong_number_detected"] == False) &
        (scored_df["inside_calling_hours"] == True)
    )

    scored_df["summary_note"] = scored_df.apply(
        lambda row: (
            f"War Room OS Lead Summary | "
            f"Status: {row['lead_status']} | "
            f"Score: {row['lead_score']} | "
            f"Motivation: {row['motivation']} | "
            f"Seller Message: {row['seller_message']}"
        ),
        axis=1
    )

    return scored_df


# =========================
# ZAPIER / REI BLACKBOOK PUSH
# =========================

def send_to_zapier(row):
    if not ZAPIER_WEBHOOK_URL:
        return False, "No Zapier webhook URL saved yet."

    payload = {
        "seller_name": row.get("seller_name", ""),
        "phone": row.get("clean_phone", row.get("phone", "")),
        "email": row.get("email", ""),
        "property_address": row.get("property_address", ""),
        "campaign_name": row.get("campaign_name", ""),
        "source": row.get("source", "XLeads"),
        "seller_message": row.get("seller_message", ""),
        "lead_status": row.get("lead_status", ""),
        "lead_score": int(row.get("lead_score", 0)),
        "motivation": row.get("motivation", ""),
        "call_permission": row.get("call_permission", ""),
        "ai_call_allowed": str(row.get("ai_call_allowed", False)),
        "recommended_next_step": row.get("recommended_next_step", ""),
        "recommended_next_question": row.get("recommended_next_question", ""),
        "rei_blackbook_tag": row.get("rei_blackbook_tag", ""),
        "rei_blackbook_workflow": row.get("rei_blackbook_workflow", ""),
        "summary_note": row.get("summary_note", "")
    }

    try:
        response = requests.post(ZAPIER_WEBHOOK_URL, json=payload, timeout=15)
        if response.status_code in [200, 201, 202]:
            return True, "Sent to Zapier successfully."
        return False, f"Zapier returned status code {response.status_code}: {response.text}"
    except Exception as e:
        return False, str(e)


# =========================
# STREAMLIT APP
# =========================

st.title(APP_TITLE)
st.subheader(MODULE_TITLE)

st.write(
    "This module sorts XLeads replies, finds hot sellers, builds a follow-up queue, "
    "checks call compliance, and prepares hot leads for REI BlackBook."
)

st.divider()

with st.expander("CSV columns to use"):
    st.code(
        "seller_name,phone,email,property_address,seller_message,campaign_name,source,seller_timezone",
        language="text"
    )

uploaded_file = st.file_uploader("Upload XLeads replies CSV", type=["csv"])

if uploaded_file is None:
    st.warning("Upload a CSV to begin.")
    st.stop()

df = pd.read_csv(uploaded_file)
df = normalize_columns(df)

st.write("### Raw XLeads Replies")
st.dataframe(df, use_container_width=True)

if st.button("Score Leads With War Room OS", type="primary"):
    st.session_state["scored_df"] = score_dataframe(df)

if "scored_df" not in st.session_state:
    st.stop()

scored_df = st.session_state["scored_df"]

total = len(scored_df)
hot = len(scored_df[scored_df["lead_status"] == "Hot A Lead"])
warm = len(scored_df[scored_df["lead_status"] == "Warm B Lead"])
nurture = len(scored_df[scored_df["lead_status"] == "Nurture C Lead"])
blocked = len(scored_df[scored_df["lead_status"].isin(["DNC / Opt-Out", "Wrong Number"])])
ai_allowed = len(scored_df[scored_df["ai_call_allowed"] == True])

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Leads", total)
col2.metric("Hot Leads", hot)
col3.metric("Warm Leads", warm)
col4.metric("Blocked", blocked)
col5.metric("AI Calls Allowed", ai_allowed)

tabs = st.tabs([
    "Hot Leads",
    "Follow-Up Queue",
    "Compliance Call Manager",
    "All Scored Leads",
    "REI BlackBook Push"
])

with tabs[0]:
    st.write("### Hot Leads")
    hot_df = scored_df[scored_df["lead_status"] == "Hot A Lead"].sort_values("lead_score", ascending=False)
    st.dataframe(hot_df, use_container_width=True)

with tabs[1]:
    st.write("### Follow-Up Queue")
    follow_df = scored_df[
        scored_df["lead_status"].isin(["Warm B Lead", "Nurture C Lead", "Needs Review"])
    ].sort_values("lead_score", ascending=False)
    st.dataframe(follow_df, use_container_width=True)

with tabs[2]:
    st.write("### Compliance Call Manager")
    st.warning(
        "AI calls are allowed only when the seller clearly gave call permission, "
        "did not opt out, is not a wrong number, and it is inside calling hours."
    )

    compliance_cols = [
        "seller_name",
        "phone",
        "property_address",
        "seller_message",
        "lead_status",
        "call_permission",
        "opt_out_detected",
        "wrong_number_detected",
        "inside_calling_hours",
        "ai_call_allowed",
        "human_call_task_allowed"
    ]

    st.dataframe(scored_df[compliance_cols], use_container_width=True)

with tabs[3]:
    st.write("### All Scored Leads")
    st.dataframe(scored_df, use_container_width=True)

    csv = scored_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Scored Leads CSV",
        csv,
        "war_room_scored_leads.csv",
        "text/csv"
    )

with tabs[4]:
    st.write("### Push Hot Leads to REI BlackBook Through Zapier")
    st.caption(
        "This sends hot leads to a Zapier webhook. Zapier will then create/update the contact in REI BlackBook."
    )

    hot_push_df = scored_df[
        (scored_df["lead_status"] == "Hot A Lead") &
        (scored_df["opt_out_detected"] == False) &
        (scored_df["wrong_number_detected"] == False)
    ].copy()

    st.dataframe(hot_push_df, use_container_width=True)

    if st.button("Send Hot Leads to Zapier / REI BlackBook"):
        results = []

        for _, row in hot_push_df.iterrows():
            success, message = send_to_zapier(row)
            results.append({
                "seller_name": row.get("seller_name", ""),
                "phone": row.get("phone", ""),
                "property_address": row.get("property_address", ""),
                "success": success,
                "message": message
            })

        st.write("### Push Results")
        st.dataframe(pd.DataFrame(results), use_container_width=True)
