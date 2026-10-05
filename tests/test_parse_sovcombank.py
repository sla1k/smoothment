from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.statement.model import StatementFormatError
from smoothment.statement.parsers import sovcombank

HEADER = list(sovcombank.HEADER)

ROWS: list[list[str]] = [
    HEADER,
    ["", "Собственные средства", "", "", ""],
    ["14.09.2026 12:26", "-0,09", "", "Комиссия за операцию", ""],
    ["13.09.2026 18:00", "+32\xa0500,00", "325", "Пополнение счета", ""],
    ["12.09.2026 09:15", "+400,00", "4", "sample.shop.example", "*1234"],
    ["11.09.2026 08:00", "-1 500,00", "", "Прочая операция", ""],
    ["", "", "", "", ""],
]


def test_row_count_and_input_rows() -> None:
    statement = sovcombank.parse_rows(ROWS, Path("statement.xls"), "Main")

    assert statement.bank == "sovcombank"
    assert statement.kind == "current"
    assert len(statement.rows) == 4
    assert statement.input_rows == 5
    assert statement.chains == ()
    for row in statement.rows:
        assert isinstance(row.amount, Decimal)


def test_section_row_is_skipped() -> None:
    statement = sovcombank.parse_rows(ROWS, Path("statement.xls"), "Main")

    assert len(statement.skipped) == 1
    skipped = statement.skipped[0]
    assert skipped.line == 2
    assert skipped.reason == "section header"
    assert skipped.text == "Собственные средства"


def test_amounts_and_date() -> None:
    statement = sovcombank.parse_rows(ROWS, Path("statement.xls"), "Main")
    rows = statement.rows

    assert rows[0].amount == Decimal("-0.09")
    assert rows[0].date == datetime(2026, 9, 14, 12, 26)
    assert rows[0].has_time is True
    assert rows[0].currency == "RUB"

    assert rows[1].amount == Decimal("32500.00")
    assert rows[3].amount == Decimal("-1500.00")


def test_card_row_sets_counterparty_and_reference() -> None:
    statement = sovcombank.parse_rows(ROWS, Path("statement.xls"), "Main")
    card_row = statement.rows[2]

    assert card_row.counterparty == "sample.shop.example"
    assert card_row.reference == "*1234"


def test_non_card_rows_have_no_counterparty() -> None:
    statement = sovcombank.parse_rows(ROWS, Path("statement.xls"), "Main")

    assert statement.rows[0].counterparty is None
    assert statement.rows[0].reference is None
    assert statement.rows[1].counterparty is None
    assert statement.rows[3].counterparty is None


def test_cashback_only_row_is_skipped_not_dropped() -> None:
    rows = [HEADER, ["", "", "325", "", ""]]

    statement = sovcombank.parse_rows(rows, Path("statement.xls"), "Main")

    assert len(statement.rows) == 0
    assert len(statement.skipped) == 1
    skipped = statement.skipped[0]
    assert skipped.line == 2
    assert skipped.reason == "section header"
    assert skipped.text == "325"
    assert statement.input_rows == 1


def test_wrong_header_raises() -> None:
    rows = [["Wrong", "Header", "Row", "Here", "Too"]]

    with pytest.raises(StatementFormatError) as exc:
        sovcombank.parse_rows(rows, Path("statement.xls"), "Main")

    assert exc.value.row == 1
    assert exc.value.column == "header"


def test_bad_amount_raises() -> None:
    rows = [HEADER, ["14.09.2026 12:26", "abc", "", "Комиссия за операцию", ""]]

    with pytest.raises(StatementFormatError) as exc:
        sovcombank.parse_rows(rows, Path("statement.xls"), "Main")

    assert exc.value.row == 2
    assert exc.value.column == sovcombank.HEADER[1]


def test_dateless_row_with_a_numeric_amount_raises_on_the_date_column() -> None:
    rows = [HEADER, ["", "-1 500,00", "", "Прочая операция", ""]]

    with pytest.raises(StatementFormatError) as exc:
        sovcombank.parse_rows(rows, Path("statement.xls"), "Main")

    assert exc.value.row == 2
    assert exc.value.column == sovcombank.HEADER[0]


def test_dateless_row_with_a_label_stays_a_skipped_line() -> None:
    rows = [HEADER, ["", "Бонусные баллы", "", "", ""]]

    statement = sovcombank.parse_rows(rows, Path("statement.xls"), "Main")

    assert statement.rows == ()
    assert [skipped.text for skipped in statement.skipped] == ["Бонусные баллы"]


def test_card_row_with_empty_description_has_no_counterparty() -> None:
    rows = [HEADER, ["12.09.2026 09:15", "+400,00", "4", "", "*1234"]]

    statement = sovcombank.parse_rows(rows, Path("statement.xls"), "Main")

    assert statement.rows[0].counterparty is None
    assert statement.rows[0].reference == "*1234"
