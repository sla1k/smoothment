from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.statement.balance import BalanceMismatch, check_balances
from smoothment.statement.model import BalanceChain, ParsedStatement, StatementRow


def _row(line: int, date: datetime, amount: Decimal, balance: Decimal | None) -> StatementRow:
    return StatementRow(
        bank="revolut",
        account="Main",
        line=line,
        date=date,
        has_time=True,
        amount=amount,
        currency="EUR",
        description="test row",
        balance=balance,
    )


def _statement(rows: tuple[StatementRow, ...], chains: tuple[BalanceChain, ...]) -> ParsedStatement:
    return ParsedStatement(
        file=Path("revolut.csv"),
        bank="revolut",
        kind="current",
        account="Main",
        rows=rows,
        input_rows=len(rows),
        chains=chains,
    )


def test_consistent_chain_has_no_mismatches() -> None:
    rows = (
        _row(1, datetime(2026, 1, 1), Decimal("10.00"), Decimal("100.00")),
        _row(2, datetime(2026, 1, 2), Decimal("-5.00"), Decimal("95.00")),
        _row(3, datetime(2026, 1, 3), Decimal("2.00"), Decimal("97.00")),
    )
    statement = _statement(rows, (BalanceChain(name="Main", indexes=(0, 1, 2)),))
    assert check_balances(statement) == ()


def test_first_broken_link_is_reported_once() -> None:
    rows = (
        _row(1, datetime(2026, 1, 1), Decimal("10.00"), Decimal("100.00")),
        _row(3, datetime(2026, 1, 2), Decimal("-5.00"), Decimal("999.00")),
        _row(5, datetime(2026, 1, 3), Decimal("2.00"), Decimal("1.00")),
    )
    statement = _statement(rows, (BalanceChain(name="Main", indexes=(0, 1, 2)),))
    mismatches = check_balances(statement)
    assert len(mismatches) == 1
    mismatch = mismatches[0]
    assert isinstance(mismatch, BalanceMismatch)
    assert mismatch.file == statement.file
    assert mismatch.chain == "Main"
    assert mismatch.row.line == 3
    assert mismatch.row is rows[1]
    assert mismatch.expected == Decimal("95.00")
    assert mismatch.found == Decimal("999.00")


def test_chain_order_is_honoured_over_row_array_order() -> None:
    # rows array is newest-first, but the chain walks it chronologically.
    rows = (
        _row(1, datetime(2026, 1, 3), Decimal("2.00"), Decimal("97.00")),
        _row(2, datetime(2026, 1, 2), Decimal("-5.00"), Decimal("95.00")),
        _row(3, datetime(2026, 1, 1), Decimal("10.00"), Decimal("100.00")),
    )
    statement = _statement(rows, (BalanceChain(name="Main", indexes=(2, 1, 0)),))
    assert check_balances(statement) == ()


def test_missing_balance_on_chain_row_raises() -> None:
    rows = (
        _row(1, datetime(2026, 1, 1), Decimal("10.00"), Decimal("100.00")),
        _row(2, datetime(2026, 1, 2), Decimal("-5.00"), None),
    )
    statement = _statement(rows, (BalanceChain(name="Main", indexes=(0, 1)),))
    with pytest.raises(ValueError, match="2"):
        check_balances(statement)


def test_no_chains_returns_empty_tuple() -> None:
    rows = (_row(1, datetime(2026, 1, 1), Decimal("10.00"), Decimal("100.00")),)
    statement = _statement(rows, ())
    assert check_balances(statement) == ()
