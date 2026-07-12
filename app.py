from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

from lead_intelligence import (
    DEFAULT_TARGET_STATES,
    clean_text,
    run_greatness_test,
    score_dataframe,
)

st.set_page_config(page_title="War Room OS", page_icon="🏠", layout="wide")
APP_TITLE = "War Room OS"
MODULE_TITLE = "Seller Lead Command — Intelligence Layer"
DEFAULT_TIMEZONE = "America/Chicago"
PRE