"""Hotfix wrapper that guarantees unique output columns for Streamlit/Arrow."""
from __future__ import annotations

from typing import Sequence

import pandas as pd

import xleads_adapter as legacy

DEFAULT_TARGET_STATES = legacy.DEFAULT_TARGET_STATES
clean_text = legacy.clean_text
run_greatness_test = legacy.run_greatness_test
score_reply_lead = legacy.score_reply_lead
score_raw_lead = legacy.score_raw_lead
select_contact = legacy.select_contact
signal = legacy.signal
truthy = legacy.truthy


def _is_blank(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip().str.lower()
    return series.isna() | text.isin(["", "nan", "none", "null", "<na>"])


def ensure_unique_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse duplicate column names, preferring the newest nonblank value.

    XLeads exports already contain normalized fields such as phone/email. The
    scoring result can also generate those fields. Pandas allows duplicate names,
    but Streamlit/pyarrow does not. This function merges duplicate-name columns
    row by row and returns a DataFrame with guaranteed unique column names.
    """
    if df.columns.is_unique:
        return df.copy()

    output = pd.DataFrame(index=df.index)
    seen: set[str] = set()
    for column in df.columns:
        name = str(column)
        if name in seen:
            continue
        seen.add(name)
        matches = df.loc[:, df.columns == column]
        if matches.shape[1] == 1:
            output[name] = matches.iloc[:, 0]
            continue

        merged = matches.iloc[:, -1].copy()
        for position in range(matches.shape[1] - 2, -1, -1):
            earlier = matches.iloc[:, position]
            merged = merged.where(~_is_blank(merged), earlier)
        output[name] = merged

    if not output.columns.is_unique:
        raise ValueError("Unable to create unique output columns")
    return output


def score_dataframe(
    df: pd.DataFrame,
    file_mode: str,
    target_states: Sequence[str] = DEFAULT_TARGET_STATES,
) -> pd.DataFrame:
    scored = legacy.score_dataframe(df, file_mode, target_states)
    return ensure_unique_columns(scored)
