from decimal import Decimal

import pytest

from smoothment.money import parse_decimal, to_decimal


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-22.91999999998177, Decimal("-22.92")),
        (103.01999999999953, Decimal("103.02")),
        (5000, Decimal("5000.00")),
        ("-560.67", Decimal("-560.67")),
        (Decimal("0.1"), Decimal("0.10")),
    ],
)
def test_to_decimal_quantizes_to_cents(
    value: float | int | str | Decimal, expected: Decimal
) -> None:
    assert to_decimal(value) == expected


def test_to_decimal_never_returns_float_artifacts() -> None:
    assert str(to_decimal(0.1 + 0.2)) == "0.30"


@pytest.mark.parametrize(
    ("text", "kwargs", "expected"),
    [
        ("-30.25", {}, Decimal("-30.25")),
        ("2,678.58", {}, Decimal("2678.58")),
        ("€1.00", {}, Decimal("1.00")),
        ("-0.0072", {}, Decimal("-0.0072")),
        (
            "+32 500,00",
            {"decimal_sep": ",", "thousands_sep": " "},
            Decimal("32500.00"),
        ),
        (
            "-31\xa0642,40",
            {"decimal_sep": ",", "thousands_sep": " "},
            Decimal("-31642.40"),
        ),
        (
            "1.234,56",
            {"decimal_sep": ",", "thousands_sep": "."},
            Decimal("1234.56"),
        ),
    ],
)
def test_parse_decimal_is_exact(text: str, kwargs: dict[str, str], expected: Decimal) -> None:
    result = parse_decimal(text, **kwargs)
    assert result == expected
    assert str(result) == str(expected)


@pytest.mark.parametrize("text", ["", "abc", "1.2.3"])
def test_parse_decimal_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError, match=r"^not a number:"):
        parse_decimal(text)


@pytest.mark.parametrize("text", ["1+2", "Infinity", "-Infinity", "NaN", "1e3", "1_000", "56,85"])
def test_parse_decimal_rejects_non_bank_number_syntax(text: str) -> None:
    with pytest.raises(ValueError, match=r"^not a number:"):
        parse_decimal(text)


@pytest.mark.parametrize("text", ["1,23", "1,2345", "12,34,567", ",123", "1.", ".5", "€1€"])
def test_parse_decimal_rejects_misplaced_separators(text: str) -> None:
    with pytest.raises(ValueError, match=r"^not a number:"):
        parse_decimal(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,234,567.89", Decimal("1234567.89")),
        ("-€1.00", Decimal("-1.00")),
        ("1.00€", Decimal("1.00")),
        ("+5", Decimal("5")),
    ],
)
def test_parse_decimal_accepts_grouped_and_symbol_forms(text: str, expected: Decimal) -> None:
    assert parse_decimal(text) == expected
