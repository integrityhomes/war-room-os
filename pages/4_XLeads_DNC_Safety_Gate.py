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


def first_matching_column(df: pd.DataFrame, names: list[str]) -> str |