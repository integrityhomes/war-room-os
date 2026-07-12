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

# Import after the original surface is available. xleads_adapter imports
# lead_intelligence as its seller-reply base, which now resolves to this package.
from xleads_adapter import (  # noqa: E402,F401
    DEFAULT_TARGET_STATES,
    clean_text,
    run_greatness_test,
    score_dataframe,
    score_raw_lead,
    score_reply_lead,
    select_contact,
    signal,
    truthy,
)
