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

HOT_REPLY_THRESHOLD = 80
WARM_REPLY_THRESHOLD = 50

RAW_PRIORITY_THRESHOLD = 70
RAW_READY_THRESHOLD = 40

ZAPIER_WEBHOOK_URL = st.secrets.get("ZAPIER_WEBHOOK_URL", "")


# =========================
# BASIC HELPERS
# =========================

def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def clean_phone(phone):
    if pd.isna(phone):
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits

def parse_price(value):
    if pd.isna(value):
        return None

    text = str(value).replace("$", "").replace(",", "").strip()

    if text.lower() in ["", "none", "nan", "null"]:
        return None

    try:
        return float(text)
    except Exception:
        return None


def price_in_buy_box(price):
    if price is None:
        return False
   
    return 5000 <= price <= 75000

def combine_address(address="", city="", state="", postal=""):
    parts = [clean_text(address), clean_text(city), clean_text(state), clean_text(postal)]
    return ", ".join([p for p in parts if p and p.lower() != "none"])


def is_company_name(name):
    name = clean_text(name).lower()
    company_words = [
        "llc", "inc", "corp", "company", "properties", "holdings",
        "investment", "investments", "trust", "estate", "group",
        "homes", "realty", "management", "capital", "partners"
    ]
    return any(word in name for word in company_words)


def detect_opt_out(message):
    message = clean_text(message).lower()
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
    message = clean_text(message).lower()
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
    message = clean_text(message).lower()
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


def find_first_existing_column(df, options):
    lower_cols = {c.lower().strip(): c for c in df.columns}
    for option in options:
        key = option.lower().strip()
        if key in lower_cols:
            return lower_cols[key]
    return None


def value_from_options(row, options):
    for option in options:
        if option in row.index:
            val = clean_text(row.get(option, ""))
            if val and val.lower() != "none":
                return val
    return ""


# =========================
# COLUMN NORMALIZATION
# =========================

def normalize_columns(df):
    df = df.copy()

    # Keep original columns but add our standard columns too.
    first_col = find_first_existing_column(df, ["FirstName", "First Name", "first_name", "seller_first_name"])
    last_col = find_first_existing_column(df, ["LastName", "Last Name", "last_name", "seller_last_name"])
    name_col = find_first_existing_column(df, ["seller_name", "Name", "Owner", "OwnerName", "FullName", "Full Name"])

    phone_col = find_first_existing_column(df, [
        "phone", "Phone", "PhoneNumber", "Phone Number", "Mobile", "MobilePhone",
        "RecipientPhone", "OwnerPhone", "PrimaryPhone", "phone1",
        "Contact1Phone_1", "Contact1Phone1", "Contact1 Phone 1",
        "Contact1Phone_2", "Contact1Phone2", "Contact1 Phone 2",
        "Contact2Phone_1", "Contact2Phone1", "Contact2 Phone 1",
        "ContactPhone", "Contact Phone"
    ])

    email_col = find_first_existing_column(df, [
        "email", "Email", "EmailAddress", "Email Address", "RecipientEmail", "OwnerEmail"
    ])

    message_col = find_first_existing_column(df, [
        "seller_message", "message", "reply", "seller_reply", "last_message",
        "sms", "body", "Text", "Conversation"
    ])

    campaign_col = find_first_existing_column(df, [
        "campaign_name", "campaign", "Campaign", "ListName", "List Name", "SourceList"
    ])

    source_col = find_first_existing_column(df, ["source", "Source"])

    timezone_col = find_first_existing_column(df, [
        "seller_timezone", "timezone", "time_zone", "TimeZone"
    ])

    prop_addr_col = find_first_existing_column(df, [
        "PropertyAddress", "Property Address", "property_address", "SiteAddress", "SitusAddress"
    ])

    prop_city_col = find_first_existing_column(df, [
        "PropertyCity", "Property City", "property_city", "SiteCity", "SitusCity"
    ])

    prop_state_col = find_first_existing_column(df, [
        "PropertyState", "Property State", "property_state", "SiteState", "SitusState"
    ])

    prop_zip_col = find_first_existing_column(df, [
        "PropertyPostalCode", "Property Zip", "PropertyZip", "property_zip", "SiteZip", "SitusZip"
    ])
    price_col = find_first_existing_column(df, [
        "Price", "price", "ListPrice", "List Price", "AskingPrice", "Asking Price",
        "EstimatedValue", "Estimated Value", "EstValue", "Est Value",
        "PropertyValue", "Property Value", "MarketValue", "Market Value",
        "AssessedValue", "Assessed Value", "AVM", "Value",
        "LastSalePrice", "Last Sale Price", "SalePrice", "Sale Price"
    ])
    mail_addr_col = find_first_existing_column(df, [
        "RecipientAddress", "MailingAddress", "Mailing Address", "OwnerAddress", "Owner Address"
    ])

    mail_city_col = find_first_existing_column(df, [
        "RecipientCity", "MailingCity", "Mailing City", "OwnerCity", "Owner City"
    ])

    mail_state_col = find_first_existing_column(df, [
        "RecipientState", "MailingState", "Mailing State", "OwnerState", "Owner State"
    ])

    mail_zip_col = find_first_existing_column(df, [
        "RecipientPostalCode", "MailingZip", "Mailing Zip", "OwnerZip", "Owner Zip"
    ])

    dnc_col = find_first_existing_column(df, [
        "DNC", "DoNotCall", "Do Not Call", "PhoneStatus", "Phone Status", "Compliance",
        "Contact1Phone_1_DNC", "Contact1Phone1DNC", "Contact1 Phone 1 DNC",
        "Contact1Phone_2_DNC", "Contact1Phone2DNC", "Contact1 Phone 2 DNC",
        "Contact2Phone_1_DNC", "Contact2Phone1DNC", "Contact2 Phone 1 DNC"
    ])
    # Seller name
    if name_col:
        df["seller_name"] = df[name_col].fillna("").astype(str)
    else:
        first = df[first_col].fillna("").astype(str) if first_col else ""
        last = df[last_col].fillna("").astype(str) if last_col else ""
        df["seller_name"] = (first + " " + last).str.strip() if first_col or last_col else ""

    # Standard fields
    df["phone"] = df[phone_col].fillna("").astype(str) if phone_col else ""
    df["email"] = df[email_col].fillna("").astype(str) if email_col else ""
    df["seller_message"] = df[message_col].fillna("").astype(str) if message_col else ""
    df["campaign_name"] = df[campaign_col].fillna("").astype(str) if campaign_col else "XLeads Export"
    df["source"] = df[source_col].fillna("").astype(str) if source_col else "XLeads"
    df["seller_timezone"] = df[timezone_col].fillna("").astype(str) if timezone_col else DEFAULT_TIMEZONE

    df["property_street"] = df[prop_addr_col].fillna("").astype(str) if prop_addr_col else ""
    df["property_city"] = df[prop_city_col].fillna("").astype(str) if prop_city_col else ""
    df["property_state"] = df[prop_state_col].fillna("").astype(str) if prop_state_col else ""
    df["property_zip"] = df[prop_zip_col].fillna("").astype(str) if prop_zip_col else ""
    df["property_price"] = df[price_col].apply(parse_price) if price_col else None
    df["mailing_street"] = df[mail_addr_col].fillna("").astype(str) if mail_addr_col else ""
    df["mailing_city"] = df[mail_city_col].fillna("").astype(str) if mail_city_col else ""
    df["mailing_state"] = df[mail_state_col].fillna("").astype(str) if mail_state_col else ""
    df["mailing_zip"] = df[mail_zip_col].fillna("").astype(str) if mail_zip_col else ""

    df["property_address"] = df.apply(
        lambda row: combine_address(
            row.get("property_street", ""),
            row.get("property_city", ""),
            row.get("property_state", ""),
            row.get("property_zip", "")
        ),
        axis=1
    )

    df["mailing_address"] = df.apply(
        lambda row: combine_address(
            row.get("mailing_street", ""),
            row.get("mailing_city", ""),
            row.get("mailing_state", ""),
            row.get("mailing_zip", "")
        ),
        axis=1
    )

    df["dnc_raw"] = df[dnc_col].fillna("").astype(str) if dnc_col else ""

    return df


def detect_file_mode(df):
    message_count = df["seller_message"].astype(str).str.strip().replace("nan", "").ne("").sum()
    if message_count > 0:
        return "Seller Replies"
    return "Raw XLeads Property List"


# =========================
# SELLER REPLY SCORING
# =========================

def score_reply_lead(row):
    message = clean_text(row.get("seller_message", "")).lower()

    if detect_opt_out(message):
        return {
            "lead_status": "DNC / Opt-Out",
            "lead_score": 0,
            "lead_lane": "Blocked",
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
            "lead_lane": "Blocked",
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

    if score >= HOT_REPLY_THRESHOLD:
        status = "Hot A Lead"
        lane = "Hot Replies"
        tag = "XLEADS_HOT_SELLER"
        workflow = "Hot Seller Immediate Call"
        next_step = "Push to REI BlackBook and create immediate call task."
    elif score >= WARM_REPLY_THRESHOLD:
        status = "Warm B Lead"
        lane = "Follow-Up Queue"
        tag = "XLEADS_WARM_SELLER"
        workflow = "Warm Seller Follow Up"
        next_step = "Keep qualifying. Ask one question at a time."
    elif score > 0:
        status = "Nurture C Lead"
        lane = "Follow-Up Queue"
        tag = "XLEADS_NURTURE"
        workflow = "Long Term Nurture"
        next_step = "Add to follow-up queue."
    else:
        status = "Needs Review"
        lane = "Review"
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
        "lead_lane": lane,
        "motivation": ", ".join(reasons) if reasons else "Not clear yet.",
        "recommended_next_step": next_step,
        "recommended_next_question": next_question,
        "rei_blackbook_tag": tag,
        "rei_blackbook_workflow": workflow,
        "call_permission": "Yes" if detect_call_permission(message) else "No"
    }


# =========================
# RAW XLEADS LIST SCORING
# =========================

def raw_dnc_detected(row):
    # Detect DNC from either column names like Contact1Phone_1_DNC
    # or values like TRUE, checked, yes, do not call, dnc, etc.
    for col in row.index:
        col_lower = clean_text(col).lower()
        val = clean_text(row.get(col, "")).lower()

        if "dnc" in col_lower or "do_not_call" in col_lower or "donotcall" in col_lower:
            if val in ["true", "yes", "1", "checked", "x"]:
                return True

    text = " ".join([clean_text(row.get(c, "")) for c in row.index]).lower()

    dnc_phrases = [
        "do not call",
        "donotcall",
        "dnc",
        "do-not-call",
        "litigator",
        "blacklist"
    ]

    return any(phrase in text for phrase in dnc_phrases)


def score_raw_xleads_lead(row):
    score = 0
    reasons = []

    seller_name = clean_text(row.get("seller_name", ""))
    property_address = clean_text(row.get("property_address", ""))
    mailing_address = clean_text(row.get("mailing_address", ""))

    prop_city = clean_text(row.get("property_city", "")).lower()
    prop_state = clean_text(row.get("property_state", "")).lower()
    prop_zip = clean_text(row.get("property_zip", ""))

    mail_city = clean_text(row.get("mailing_city", "")).lower()
    mail_state = clean_text(row.get("mailing_state", "")).lower()
    mail_zip = clean_text(row.get("mailing_zip", ""))

    phone = clean_phone(row.get("phone", ""))
    email = clean_text(row.get("email", ""))
    property_price = row.get("property_price", None)
    if raw_dnc_detected(row):
        return {
            "lead_status": "Possible DNC / Call Block",
            "lead_score": 0,
            "lead_lane": "Blocked",
            "motivation": "XLeads export contains possible DNC / do-not-call language.",
            "recommended_next_step": "Do not call. Review before any text/email.",
            "recommended_next_question": "",
            "rei_blackbook_tag": "XLEADS_DNC_REVIEW",
            "rei_blackbook_workflow": "Compliance Review",
            "call_permission": "No"
        }

    if property_address:
        score += 15
        reasons.append("property address present")
    if price_in_buy_box(property_price):
        score += 30
        reasons.append("price/value inside $5k-$75k buy box")
    elif property_price is None:
        reasons.append("no price/value found")
    elif property_price < 5000:
        score -= 10
        reasons.append("price/value under $5k - review")
    elif property_price > 75000:
        score -= 20
        reasons.append("price/value over $75k buy box")
    if phone:
        score += 20
        reasons.append("phone present")
    else:
        reasons.append("no phone found in export")

    if email:
        score += 5
        reasons.append("email present")

    if seller_name:
        score += 10
        reasons.append("owner name present")

    if is_company_name(seller_name):
        score += 15
        reasons.append("company/LLC owner")

    absentee = False

    if mailing_address and property_address:
        if mail_zip and prop_zip and mail_zip != prop_zip:
            absentee = True
        elif mail_city and prop_city and mail_city != prop_city:
            absentee = True
        elif mail_state and prop_state and mail_state != prop_state:
            absentee = True

    if absentee:
        score += 25
        reasons.append("absentee owner")

    if mail_state and prop_state and mail_state != prop_state:
        score += 15
        reasons.append("out-of-state owner")

    if seller_name.lower() in ["none", "unknown", ""]:
        score -= 10
        reasons.append("missing owner name")

    score = max(0, min(score, 100))

    if not phone:
        status = "Needs Phone / Skip Trace"
        lane = "Needs Data"
        tag = "XLEADS_NEEDS_SKIPTRACE"
        workflow = "Needs Skip Trace"
        next_step = "Do not call yet. Needs phone or better contact data."
    elif score >= RAW_PRIORITY_THRESHOLD:
        status = "Priority Text Lead"
        lane = "Raw Lead Prioritizer"
        tag = "XLEADS_PRIORITY_RAW_LEAD"
        workflow = "Ready For Text Campaign"
        next_step = "Good lead to send into XLeads text/email campaign."
    elif score >= RAW_READY_THRESHOLD:
        status = "Ready for Text Campaign"
        lane = "Raw Lead Prioritizer"
        tag = "XLEADS_READY_FOR_TEXT"
        workflow = "Ready For Text Campaign"
        next_step = "Okay to include in campaign after compliance review."
    else:
        status = "Property Lead Review"
        lane = "Review"
        tag = "XLEADS_PROPERTY_REVIEW"
        workflow = "Property Lead Review"
        next_step = "Review before marketing."

    return {
        "lead_status": status,
        "lead_score": score,
        "lead_lane": lane,
        "motivation": ", ".join(reasons) if reasons else "Raw property lead.",
        "recommended_next_step": next_step,
        "recommended_next_question": "",
        "rei_blackbook_tag": tag,
        "rei_blackbook_workflow": workflow,
        "call_permission": "No"
    }


def score_dataframe(df, file_mode):
    scored_rows = []

    for _, row in df.iterrows():
        if file_mode == "Seller Replies":
            result = score_reply_lead(row)
        else:
            result = score_raw_xleads_lead(row)
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
        (file_mode == "Seller Replies") &
        (scored_df["call_permission"] == "Yes") &
        (scored_df["opt_out_detected"] == False) &
        (scored_df["wrong_number_detected"] == False) &
        (scored_df["inside_calling_hours"] == True)
    )

    scored_df["human_call_task_allowed"] = (
        (file_mode == "Seller Replies") &
        (scored_df["lead_status"].isin(["Hot A Lead", "Warm B Lead"])) &
        (scored_df["opt_out_detected"] == False) &
        (scored_df["wrong_number_detected"] == False) &
        (scored_df["inside_calling_hours"] == True)
    )

    scored_df["summary_note"] = scored_df.apply(
        lambda row: (
            f"War Room OS Lead Summary | "
            f"Mode: {file_mode} | "
            f"Status: {row['lead_status']} | "
            f"Score: {row['lead_score']} | "
            f"Reason: {row['motivation']} | "
            f"Property: {row.get('property_address', '')} | "
            f"Seller Message: {row.get('seller_message', '')}"
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
        "mailing_address": row.get("mailing_address", ""),
        "campaign_name": row.get("campaign_name", ""),
        "source": row.get("source", "XLeads"),
        "seller_message": row.get("seller_message", ""),
        "lead_status": row.get("lead_status", ""),
        "lead_score": int(row.get("lead_score", 0)),
        "lead_lane": row.get("lead_lane", ""),
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
    "This module handles both raw XLeads property exports and seller reply files. "
    "Raw lists are prioritized for campaigns. Seller replies are sorted into hot leads, follow-up, and compliance queues."
)

st.divider()

with st.expander("CSV file types this app can read"):
    st.write("**Raw XLeads Property List columns:**")
    st.code(
        "FirstName, LastName, RecipientAddress, RecipientCity, RecipientState, RecipientPostalCode, PropertyAddress, PropertyCity, PropertyState, PropertyPostalCode",
        language="text"
    )

    st.write("**Seller Reply columns:**")
    st.code(
        "seller_name, phone, email, property_address, seller_message, campaign_name, source, seller_timezone",
        language="text"
    )

uploaded_file = st.file_uploader("Upload XLeads CSV", type=["csv"])

if uploaded_file is None:
    st.warning("Upload a CSV to begin.")
    st.stop()

df = pd.read_csv(uploaded_file)
df = normalize_columns(df)
file_mode = detect_file_mode(df)

st.success(f"Detected file type: {file_mode}")

st.write("### Raw Uploaded Data")
st.dataframe(df.head(25), use_container_width=True)

if st.button("Score Leads With War Room OS", type="primary"):
    st.session_state["scored_df"] = score_dataframe(df, file_mode)
    st.session_state["file_mode"] = file_mode

if "scored_df" not in st.session_state:
    st.stop()

scored_df = st.session_state["scored_df"]
file_mode = st.session_state["file_mode"]

total = len(scored_df)

if file_mode == "Seller Replies":
    hot = len(scored_df[scored_df["lead_status"] == "Hot A Lead"])
    warm = len(scored_df[scored_df["lead_status"] == "Warm B Lead"])
    blocked = len(scored_df[scored_df["lead_status"].isin(["DNC / Opt-Out", "Wrong Number"])])
    ai_allowed = len(scored_df[scored_df["ai_call_allowed"] == True])

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Replies", total)
    col2.metric("Hot Leads", hot)
    col3.metric("Warm Leads", warm)
    col4.metric("Blocked", blocked)
    col5.metric("AI Calls Allowed", ai_allowed)

else:
    priority = len(scored_df[scored_df["lead_status"] == "Priority Text Lead"])
    ready = len(scored_df[scored_df["lead_status"] == "Ready for Text Campaign"])
    needs_data = len(scored_df[scored_df["lead_status"] == "Needs Phone / Skip Trace"])
    blocked = len(scored_df[scored_df["lead_status"] == "Possible DNC / Call Block"])

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Raw Leads", total)
    col2.metric("Priority Text Leads", priority)
    col3.metric("Ready for Campaign", ready)
    col4.metric("Needs Data", needs_data)
    col5.metric("Blocked Review", blocked)

tabs = st.tabs([
    "Priority Leads",
    "Follow-Up / Review",
    "Compliance Call Manager",
    "All Scored Leads",
    "REI BlackBook Push"
])

with tabs[0]:
    if file_mode == "Seller Replies":
        st.write("### Hot Seller Replies")
        view_df = scored_df[scored_df["lead_status"] == "Hot A Lead"].sort_values("lead_score", ascending=False)
    else:
        st.write("### Priority Raw XLeads Leads")
        view_df = scored_df[
            scored_df["lead_status"].isin(["Priority Text Lead", "Ready for Text Campaign"])
        ].sort_values("lead_score", ascending=False)

    st.dataframe(view_df, use_container_width=True)

with tabs[1]:
    st.write("### Follow-Up / Review Queue")
    if file_mode == "Seller Replies":
        view_df = scored_df[
            scored_df["lead_status"].isin(["Warm B Lead", "Nurture C Lead", "Needs Review"])
        ].sort_values("lead_score", ascending=False)
    else:
        view_df = scored_df[
            scored_df["lead_status"].isin(["Needs Phone / Skip Trace", "Property Lead Review"])
        ].sort_values("lead_score", ascending=False)

    st.dataframe(view_df, use_container_width=True)

with tabs[2]:
    st.write("### Compliance Call Manager")
    st.warning(
        "AI calls are only allowed for seller reply files when the seller clearly gave call permission, "
        "did not opt out, is not a wrong number, and it is inside calling hours. "
        "Raw XLeads lists should not be AI-called."
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

    existing_cols = [c for c in compliance_cols if c in scored_df.columns]
    st.dataframe(scored_df[existing_cols], use_container_width=True)

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
    st.write("### Push Leads to REI BlackBook Through Zapier")
    st.caption(
        "For now, only push seller replies or reviewed priority leads. Zapier will create/update the contact in REI BlackBook."
    )

    if file_mode == "Seller Replies":
        push_df = scored_df[
            (scored_df["lead_status"] == "Hot A Lead") &
            (scored_df["opt_out_detected"] == False) &
            (scored_df["wrong_number_detected"] == False)
        ].copy()
    else:
        push_df = scored_df[
            (scored_df["lead_status"] == "Priority Text Lead")
        ].copy()

    st.dataframe(push_df, use_container_width=True)

    if st.button("Send These Leads to Zapier / REI BlackBook"):
        results = []

        for _, row in push_df.iterrows():
            success, message = send_to_zapier(row)
            results.append({
                "seller_name": row.get("seller_name", ""),
                "phone": row.get("phone", ""),
                "property_address": row.get("property_address", ""),
                "lead_status": row.get("lead_status", ""),
                "success": success,
                "message": message
            })

        st.write("### Push Results")
        st.dataframe(pd.DataFrame(results), use_container_width=True)
