"""Lead intelligence package entrypoint.

Loads the tested seller-reply engine from the legacy module and overlays the
real-XLeads raw export adapter plus the unique-column Streamlit hotfix.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_BASE_PATH = Path(__file__).resolve().parent.parent / "lead_intelligence.py"
_SPEC = importlib.util.spec_from_file_location("_war_room_lead_intelligence_base", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load lead intelligence core from {_BASE_PATH}")
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)

for _name in dir(_BASE):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_BASE, _name)

import xleads_adapter as _ADAPTER  # noqa: E402

_ADAPTER.base = _BASE

import xleads_adapter_v2 as _HOTFIX  # noqa: E402

DEFAULT_TARGET_STATES = _HOTFIX.DEFAULT_TARGET_STATES
clean_text = _HOTFIX.clean_text
run_greatness_test = _HOTFIX.run_greatness_test
score_dataframe = _HOTFIX.score_dataframe
score_raw_lead = _HOTFIX.score_raw_lead
score_reply_lead = _HOTFIX.score_reply_lead
select_contact = _HOTFIX.select_contact
signal = _HOTFIX.signal
truthy = _HOTFIX.truthy
ensure_unique_columns = _HOTFIX.ensure_unique_columns
