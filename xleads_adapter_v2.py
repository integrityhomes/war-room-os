"""Stable wrapper that guarantees unique output columns for Streamlit."""
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
    """Collapse duplicate names without repeatedly inserting columns.

    The previous implementation inserted one column at a time, producing a highly
    fragmented DataFrame. On Streamlit Community Cloud that path eventually caused
    the Python process to segfault. This version builds all Series first and performs
    one concat operation.
    """
    if df.columns.is_unique:
        return df.copy(deep=False)

    series_list: list[pd.Series] = []
    seen: set[str] = set()

    for column in df.columns:
        name = str(column)
        if name in seen:
            continue
        seen.add(name)

        matches = df.loc[:, df.columns == column]
        if matches.shape[1] == 1:
            merged = matches.iloc[:, 0].copy()
        else:
            merged = matches.iloc[:, -1].copy()
            for position in range(matches.shape[1] - 2, -1, -1):
                earlier = matches.iloc[:, position]
                merged = merged.where(~_is_blank(merged), earlier)

        merged.name = name
        series_list.append(merged)

    output = pd.concat(series_list, axis=1, copy=False)
    if not output.columns.is_unique:
        raise ValueError("Unable to create unique output columns")
    return output.copy()


def score_dataframe(
    df: pd.DataFrame,
    file_mode: str,
    target_states: Sequence[str] = DEFAULT_TARGET_STATES,
) -> pd.DataFrame:
    scored = legacy.score_dataframe(df, file_mode, target_states)
    return ensure_unique_columns(scored)
