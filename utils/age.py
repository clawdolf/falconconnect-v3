"""Age and LAge (lead age) calculation utilities — ported from FC v2."""

from datetime import date, datetime
from typing import Optional

from dateutil.relativedelta import relativedelta


def calculate_age(birth_year: int) -> int:
    """Calculate current age in years from birth year.

    Assumes birthday has already occurred this year for simplicity.
    """
    current_year = datetime.now().year
    return current_year - birth_year


def calculate_lage(mail_date_str: Optional[str]) -> Optional[int]:
    """Calculate LAge — months since the mail/lead date.

    Args:
        mail_date_str: ISO date string (YYYY-MM-DD) of the original mail drop.

    Returns:
        Number of whole months since mail_date, or None if input is invalid.
    """
    if not mail_date_str:
        return None

    try:
        if isinstance(mail_date_str, date):
            mail_date = mail_date_str
        else:
            mail_date = date.fromisoformat(str(mail_date_str))
    except (ValueError, TypeError):
        return None

    today = date.today()
    if mail_date > today:
        return 0

    delta = relativedelta(today, mail_date)
    return delta.years * 12 + delta.months
