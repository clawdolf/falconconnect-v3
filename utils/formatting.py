"""Formatting utilities for display values."""

import re


def format_dollar_amount(value) -> str:
    """Convert a numeric value to formatted dollar string: $XXX,XXX (no decimals).

    Examples:
        100000 -> "$100,000"
        408000.0 -> "$408,000"
        "94627.00" -> "$94,627"
        "250,000" -> "$250,000"
        None -> ""
    """
    if value is None or value == "":
        return ""
    try:
        # Strip non-numeric except decimal
        cleaned = re.sub(r"[^\d.]", "", str(value))
        if not cleaned:
            return ""
        num = int(float(cleaned))
        return f"${num:,}"
    except (ValueError, TypeError):
        return str(value)
