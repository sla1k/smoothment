import re
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")
_SPACES = (" ", "\xa0", "\u202f")
_CURRENCY = "€"


def to_decimal(value: float | int | str | Decimal) -> Decimal:
    """Convert a value that may have come from a REAL column into exact cents."""
    raw = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    return raw.quantize(CENTS, rounding=ROUND_HALF_UP)


def _number_pattern(decimal_sep: str, thousands_sep: str) -> re.Pattern[str]:
    integer = "[0-9]+"
    if thousands_sep and thousands_sep not in _SPACES:
        integer = f"(?:[0-9]{{1,3}}(?:{re.escape(thousands_sep)}[0-9]{{3}})+|[0-9]+)"
    currency = re.escape(_CURRENCY)
    return re.compile(
        f"(?P<sign>[+-]?)(?P<lead>{currency}?)(?P<integer>{integer})"
        f"(?:{re.escape(decimal_sep)}(?P<fraction>[0-9]+))?(?P<trail>{currency}?)"
    )


def parse_decimal(text: str, *, decimal_sep: str = ".", thousands_sep: str = ",") -> Decimal:
    """Parse a bank-formatted amount exactly, with no rounding.

    After removing spaces (regular, no-break, narrow no-break), the text must be an
    optional sign, an optional euro sign, digits (optionally grouped by three with
    `thousands_sep`), an optional `decimal_sep` followed by digits, and a trailing euro
    sign only when there was no leading one. Anything else, including empty input,
    exponents, underscores, NaN and Infinity, raises ValueError("not a number: …").
    """
    cleaned = text
    for space in _SPACES:
        cleaned = cleaned.replace(space, "")
    match = _number_pattern(decimal_sep, thousands_sep).fullmatch(cleaned)
    if match is None or (match["lead"] and match["trail"]):
        raise ValueError(f"not a number: {text!r}")
    integer = match["integer"]
    if thousands_sep:
        integer = integer.replace(thousands_sep, "")
    number = match["sign"] + integer
    if match["fraction"] is not None:
        number += "." + match["fraction"]
    return Decimal(number)
