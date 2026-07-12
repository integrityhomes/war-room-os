"""Lead intelligence package entrypoint.

Loads the tested seller-reply engine from the legacy module and overlays the
real-XLeads raw export adapter. Keeping this entrypoint means the Streamlit app
and existing tests do not need import changes.
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

# Expose the complete original public surface first. This preserves seller
# reply scoring, greatness tests, helper functions, and existing test imports.
for _name in dir(_BASE):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_BASE, _name)

# Import the adapter only after the original surface is available. Then bind
# the adapter's base reference directly to the loaded legacy module so seller
# reply scoring delegates to the original function instead of recursing back
# into the adapter after this package overlays score_dataframe.
import xleads_adapter as _ADAPTER  # noqa: E402

_ADAPTER.base = _BASE

DEFAULT_TARGET_STATES = _ADAPTER.DEFAULT_TARGET_STATES
clean_text = _ADAPTER.clean_text
run_greatness_test = _ADAPTER.run_greatness_test
score_dataframe = _ADAPTER.score_dataframe
score_raw_lead = _ADAPTER.score_raw_lead
score_reply_lead = _ADAPTER.score_reply_lead
select_contact = _ADAPTER.select_contact
signal = _ADAPTER.signal
truthy = _ADAPTER.truthy
