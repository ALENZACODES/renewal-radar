"""Bounded value readers shared by broker imports and edited deal records."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

MAX_BALANCE = 100_000_000
MAX_PAYMENT = 1_000_000
MAX_TERM_MONTHS = 120
MAX_AMORT_MONTHS = 480
EARLIEST_DATE = date(1990, 1, 1)
LATEST_DATE = date(2100, 12, 31)


@dataclass(frozen=True)
class DateReading:
    value: date | None
    ambiguous: bool = False
    reason: str | None = None


def clean_text(value, maximum=160) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    text = "".join(c for c in text if c >= " " or c == "\t")
    return text[:maximum] or None


def finite_number(value, minimum=None, maximum=None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def money(value, maximum=MAX_BALANCE) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return finite_number(value, 0.01, maximum)
    if not isinstance(value, str) or len(value) > 100:
        return None
    text = value.strip()
    text = re.sub(r"(?i)\bCAD\b", "", text).replace("$", "")
    text = re.sub(r"[\s\u00a0\u202f]", "", text)
    if not text or any(c not in "0123456789,.-+" for c in text):
        return None
    if "," in text and "." in text:
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        whole, fraction = text.rsplit(decimal_separator, 1)
        if not re.fullmatch(r"\d{1,2}", fraction):
            return None
        groups = whole.split(grouping_separator)
        if len(groups) > 1 and (
            not re.fullmatch(r"[+]?\d{1,3}", groups[0])
            or any(not re.fullmatch(r"\d{3}", group) for group in groups[1:])
        ):
            return None
        text = "".join(groups) + "." + fraction
    elif "," in text:
        groups = text.split(",")
        if len(groups) == 2 and len(groups[1]) in (1, 2):
            text = groups[0] + "." + groups[1]
        elif (
            re.fullmatch(r"[+]?\d{1,3}", groups[0])
            and all(re.fullmatch(r"\d{3}", group) for group in groups[1:])
        ):
            text = "".join(groups)
        else:
            return None
    elif text.count(".") > 1:
        groups = text.split(".")
        if not (
            re.fullmatch(r"[+]?\d{1,3}", groups[0])
            and all(re.fullmatch(r"\d{3}", group) for group in groups[1:])
        ):
            return None
        text = "".join(groups)
    if not re.fullmatch(r"[+]?\d+(?:\.\d{1,2})?", text):
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite() or not Decimal("0") < amount <= Decimal(str(maximum)):
        return None
    return float(amount)


def percentage(value, *, fraction_allowed=True, allow_zero=False, maximum=30) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    explicit_percent = text.endswith("%")
    if "%" in text[:-1] or len(text) > 40:
        return None
    text = text.rstrip("%").strip().replace(",", ".")
    if not re.fullmatch(r"[+]?\d+(?:\.\d+)?", text):
        return None
    result = finite_number(text, 0, maximum)
    if result is None:
        return None
    if fraction_allowed and not explicit_percent and 0 < result < 0.3:
        result *= 100
    if not allow_zero and result == 0:
        return None
    return round(result, 6) if result <= maximum else None


def duration(value, unit_hint="", *, amortization=False) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).lower().strip()
    hint = str(unit_hint).lower()
    if len(text) > 60:
        return None
    pattern = r"(?:(\d+(?:\.\d+)?)\s*(?:years?|yrs?|y|ans?))?\s*(?:(\d+(?:\.\d+)?)\s*(?:months?|mos?|m|mois))?"
    match = re.fullmatch(pattern, text)
    if match and any(match.groups()):
        years, months = match.groups()
        number = float(years or 0) * 12 + float(months or 0)
    else:
        number = finite_number(text, 0.001, 1000)
        if number is None:
            return None
        if "month" in hint or "mois" in hint:
            pass
        elif "year" in hint or "ans" in hint:
            number *= 12
        elif number <= (40 if amortization else 10):
            number *= 12
    maximum = MAX_AMORT_MONTHS if amortization else MAX_TERM_MONTHS
    if not math.isclose(number, round(number), abs_tol=1e-7):
        return None
    return int(number) if 1 <= number <= maximum else None


def read_date(value, order: str | None = None) -> DateReading:
    if isinstance(value, datetime):
        candidate = value.date()
    elif isinstance(value, date):
        candidate = value
    elif value in (None, "") or isinstance(value, bool):
        return DateReading(None, reason="date not supplied")
    else:
        text = str(value).strip()
        if len(text) > 60:
            return DateReading(None, reason="invalid date")
        if re.match(r"^\d{4}-\d{2}-\d{2}[T ]", text):
            text = text[:10]
        numeric = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
        if numeric:
            first, second, year = map(int, numeric.groups())
            ambiguous = first <= 12 and second <= 12 and first != second
            if ambiguous and order not in ("day_first", "month_first"):
                return DateReading(None, True, "ambiguous numeric date: choose day/month or month/day")
            day_first = order == "day_first" if order is not None else first > 12
            month, day = (second, first) if day_first else (first, second)
            try:
                candidate = date(year, month, day)
            except ValueError:
                return DateReading(None, reason="invalid calendar date")
        else:
            formats = (
                "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d",
                "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y",
                "%d-%b-%Y",
            )
            candidate = None
            for fmt in formats:
                try:
                    candidate = datetime.strptime(text, fmt).date()
                    break
                except ValueError:
                    continue
            if candidate is None:
                number = finite_number(text, 20000, 73415)
                if number is not None and number.is_integer():
                    candidate = date(1899, 12, 30) + timedelta(days=int(number))
            if candidate is None:
                return DateReading(None, reason="unrecognized date")
    if not EARLIEST_DATE <= candidate <= LATEST_DATE:
        return DateReading(None, reason="date outside 1990 through 2100")
    return DateReading(candidate)


def infer_date_order(values) -> tuple[str | None, bool]:
    found = set()
    for value in values:
        match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-]\d{4}", str(value or "").strip())
        if match:
            first, second = map(int, match.groups())
            if first > 12 and second <= 12:
                found.add("day_first")
            elif second > 12 and first <= 12:
                found.add("month_first")
    return (next(iter(found)) if len(found) == 1 else None, len(found) > 1)


FREQUENCIES = {
    "monthly": "monthly", "month": "monthly", "12": "monthly",
    "semi monthly": "semi_monthly", "semimonthly": "semi_monthly", "twice monthly": "semi_monthly",
    "biweekly": "biweekly", "bi weekly": "biweekly", "fortnightly": "biweekly", "26": "biweekly",
    "weekly": "weekly", "week": "weekly", "52": "weekly",
    "accelerated biweekly": "accelerated_biweekly",
    "accelerated bi weekly": "accelerated_biweekly",
    "accelerated weekly": "accelerated_weekly",
}


def payment_frequency(value) -> str | None:
    text = clean_text(value, 60)
    if text is None:
        return None
    normalized = re.sub(r"[-_\s]+", " ", text.lower()).strip()
    return FREQUENCIES.get(normalized)


def rate_kind(value) -> str | None:
    text = clean_text(value, 120)
    if text is None:
        return None
    words = set(re.findall(r"[a-z]+", text.lower()))
    if words & {"variable", "adjustable", "arm", "vrm", "prime", "floating", "var"}:
        return "variable"
    if words & {"fixed", "fix", "fixe"}:
        return "fixed"
    return None


def contract_is_open(value) -> bool | None:
    text = clean_text(value, 160)
    if text is None:
        return None
    words = set(re.findall(r"[a-z]+", text.lower()))
    if words & {"open", "ouvert"}:
        return True
    if words & {"closed", "ferme"}:
        return False
    return None


def csv_cell(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value
