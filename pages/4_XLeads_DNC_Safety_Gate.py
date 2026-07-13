from __future__ import annotations

import re

import pandas as pd
import streamlit as st

st.set_page_config(page_title="XLeads DNC Safety Gate", page_icon="🛡️", layout="wide")

CLEAR_VALUES = {"clear", "cleared", "no", "false", "0", "not listed", "not on dnc", "approved", "ok", "pass", "passed"}
BLOCK_VALUES = {"yes", "true", "1", "listed", "on dnc", "blocked