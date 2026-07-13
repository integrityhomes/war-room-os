from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Automatic Skip Trace", page_icon="🔎", layout="wide")

SHEET_ID = "1c3F6mwJwN-EnCKeTxw16f2EfcEAxh4H6WDQPDVkyPrc"
SHEET_GID = "0"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?gid={SHEET_GID}#gid