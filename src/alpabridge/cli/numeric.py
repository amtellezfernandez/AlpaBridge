"""Shared numeric coercion for CLI commands that read counts out of JSON
summaries (batch/benchmark/promote). Centralized here after the same
near-identical helper was independently duplicated across four commands,
each missing a slightly different piece of the same safety check - most
recently, none of them caught the OverflowError int(float('inf')) raises,
so a single non-finite count anywhere in a summary could crash a report
command instead of being treated as an invalid/missing value.
"""

from __future__ import annotations

from typing import Any


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def int_or_zero(value: Any) -> int:
    parsed = optional_int(value)
    return 0 if parsed is None else parsed
