from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.statement.model import (
    BalanceChain,
    ParsedStatement,
    SkippedLine,
    StatementFormatError,
    StatementRow,
    file_order,
    parse_cell,
    single_chain,
)


def _row(line: int, date: datetime, balance: Decimal | None = None) -> StatementRow:
    return StatementRow(
        bank="revolut",
        account="Main",
        line=line,
        date=date,
        has_time=True,
        amount=Decimal("1.00"),
        currency="EUR",
        description="test row",
        balance=balance,
    )


def test_statement_format_error_message() -> None:
    err = StatementFormatError(
        file=Path("revolut.csv"),
        row=5,
        column="Amount",
        expected="decimal",
        found="abc",
    )
    assert str(err) == "revolut.csv row 5, column Amount: expected decimal, found abc"


def test_input_rows_is_carried_independently_of_rows_and_skipped() -> None:
    rows = (_row(1, datetime(2026, 1, 1)), _row(2, datetime(2026, 1, 2)))
    skipped = (SkippedLine(line=3, text="Statement summary", reason="not a transaction"),)
    statement = ParsedStatement(
        file=Path("revolut.csv"),
        bank="revolut",
        kind="current",
        account="Main",
        rows=rows,
        input_rows=4,
        skipped=skipped,
    )
    assert statement.input_rows == 4
    assert not hasattr(statement, "source_rows")


def test_file_order_newest_first_is_reversed() -> None:
    rows = [
        _row(1, datetime(2026, 1, 3)),
        _row(2, datetime(2026, 1, 2)),
        _row(3, datetime(2026, 1, 1)),
    ]
    assert file_order(rows) == (2, 1, 0)


def test_file_order_oldest_first_is_unchanged() -> None:
    rows = [
        _row(1, datetime(2026, 1, 1)),
        _row(2, datetime(2026, 1, 2)),
        _row(3, datetime(2026, 1, 3)),
    ]
    assert file_order(rows) == (0, 1, 2)


def test_file_order_single_row() -> None:
    rows = [_row(1, datetime(2026, 1, 1))]
    assert file_order(rows) == (0,)


def test_file_order_empty() -> None:
    assert file_order([]) == ()


def test_file_order_tie_keeps_file_order_by_default() -> None:
    rows = [_row(1, datetime(2026, 1, 1)), _row(2, datetime(2026, 1, 1))]
    assert file_order(rows) == (0, 1)


def test_file_order_tie_reverses_when_newest_first_on_tie() -> None:
    rows = [_row(1, datetime(2026, 1, 1)), _row(2, datetime(2026, 1, 1))]
    assert file_order(rows, newest_first_on_tie=True) == (1, 0)


def test_file_order_flag_does_not_override_distinct_dates() -> None:
    rows = [_row(1, datetime(2026, 1, 1)), _row(2, datetime(2026, 1, 2))]
    assert file_order(rows, newest_first_on_tie=True) == (0, 1)


def test_parse_cell_returns_the_parsed_value() -> None:
    assert parse_cell("12", int, file=Path("a.csv"), row=3, column="N", expected="int") == 12


def test_parse_cell_names_the_column_on_failure() -> None:
    with pytest.raises(StatementFormatError) as exc:
        parse_cell("x", int, file=Path("a.csv"), row=3, column="N", expected="int")
    assert (exc.value.row, exc.value.column, exc.value.expected, exc.value.found) == (
        3,
        "N",
        "int",
        "x",
    )


def test_single_chain_walks_rows_with_a_balance_chronologically() -> None:
    rows = [
        _row(1, datetime(2026, 1, 2), Decimal("5.00")),
        _row(2, datetime(2026, 1, 2)),
        _row(3, datetime(2026, 1, 1), Decimal("4.00")),
    ]
    assert single_chain("EUR", rows, newest_first_on_tie=True) == (
        BalanceChain(name="EUR", indexes=(2, 0)),
    )


def test_single_chain_is_empty_without_balances() -> None:
    assert single_chain("EUR", [], newest_first_on_tie=True) == ()
    assert single_chain("EUR", [_row(1, datetime(2026, 1, 1))], newest_first_on_tie=True) == ()
