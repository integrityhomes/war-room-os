from __future__ import annotations

import hashlib
import io
import re

import pandas as pd
import requests
import streamlit as st

from lead_intelligence import DEFAULT_TARGET_STATES, score_dataframe

st.set_page_config(page_title="Return Results & Rerank", page_icon="🔁", layout="wide")

SHEET_ID = "1c3F6mwJwN-EnCKeTxw16f2EfcEAxh4H6WDQPDVkyPrc"
SHEET_GID = "0"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={SHEET_GID}"
TRUTHY = {"1", "true", "yes", "y", "dnc", "blocked", "stop"}


def clean_text(value) -> str:
    if