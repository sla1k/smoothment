from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.statement.balance import check_balances
from smoothment.statement.model import StatementFormatError
from smoothment.statement.parsers import revolut
from tests.conftest import FIXTURES


def test_current_row_count_and_line_numbers() -> None:
    statement = revolut.parse_current(FIXTURES / "revolut_pockets.csv", "Main", None)
    assert statement.bank == "revolut"
    assert statement.kind == "current"
    assert len(statement.rows) == 12
    assert [row.line for row in statement.rows] == list(range(2, 14))
    for row in statement.rows:
        assert isinstance(row.amount, Decimal)


def test_current_fee_row_nets_amount_and_type() -> None:
    statement = revolut.parse_current(FIXTURES / "revolut_pockets.csv", "Main", None)
    fee_row = statement.rows[3]
    assert fee_row.amount == Decimal("-15.99")
    assert fee_row.bank_type == "Charge"


def test_current_first_row_date_and_time_flag() -> None:
    statement = revolut.parse_current(FIXTURES / "revolut_pockets.csv", "Main", None)
    first = statement.rows[0]
    assert first.date == datetime(2026, 8, 1, 10, 0, 0)
    assert first.has_time is True


def test_current_states_and_balance_for_pending_and_reverted() -> None:
    statement = revolut.parse_current(FIXTURES / "revolut_pockets.csv", "Main", None)
    states = [row.state for row in statement.rows]
    assert states == [
        "settled",
        "settled",
        "settled",
        "settled",
        "settled",
        "settled",
        "settled",
        "settled",
        "settled",
        "pending",
        "reverted",
        "settled",
    ]
    pending_row = statement.rows[9]
    reverted_row = statement.rows[10]
    assert pending_row.state == "pending" and pending_row.balance is None
    assert reverted_row.state == "reverted" and reverted_row.balance is None


def test_current_pocket_tagging() -> None:
    statement = revolut.parse_current(FIXTURES / "revolut_pockets.csv", "Main", None)
    indexes = (1, 2, 6, 7, 8)  # rows 2, 3, 7, 8, 9 (1-based data rows)
    expected_pocket_side = (False, True, True, False, True)
    for index, pocket_side in zip(indexes, expected_pocket_side, strict=True):
        row = statement.rows[index]
        assert row.pocket == "Travel"
        assert row.pocket_side is pocket_side
        assert row.counterparty is None


def test_current_counterparties() -> None:
    statement = revolut.parse_current(FIXTURES / "revolut_pockets.csv", "Main", None)
    assert statement.rows[4].counterparty == "Alex Example"  # row 5
    assert statement.rows[5].counterparty == "Sample Owner"  # row 6
    assert statement.rows[11].counterparty == "Alex Example"  # row 12
    assert statement.rows[0].counterparty is None  # card payment, row 1


def test_current_chains_and_balances_check_out() -> None:
    statement = revolut.parse_current(FIXTURES / "revolut_pockets.csv", "Main", None)
    chains = {chain.name: chain.indexes for chain in statement.chains}
    assert chains == {
        "Current": (0, 1, 3, 4, 5, 7, 11),
        "Deposit": (2, 6, 8),
    }
    assert check_balances(statement) == ()


def test_current_balance_mismatch_is_reported(tmp_path: Path) -> None:
    original = (FIXTURES / "revolut_pockets.csv").read_text(encoding="utf-8")
    broken = original.replace("164.01", "164.02")
    path = tmp_path / "revolut_pockets_broken.csv"
    path.write_text(broken, encoding="utf-8")

    statement = revolut.parse_current(path, "Main", None)
    mismatches = check_balances(statement)
    assert len(mismatches) == 1
    mismatch = mismatches[0]
    assert mismatch.row.line == 13
    assert mismatch.expected == Decimal("164.01")


def test_current_older_style_fund_and_prefunding_rows(tmp_path: Path) -> None:
    content = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "TRANSFER,Current,2026-01-01 09:00:00,2026-01-01 09:00:00,"
        "To EUR Flexible Cash Funds,-50.00,0.00,EUR,COMPLETED,50.00\n"
        "TRANSFER,Savings,2026-01-01 09:00:00,2026-01-01 09:00:00,"
        "To EUR Flexible Cash Funds,50.00,0.00,EUR,COMPLETED,50.00\n"
        "TRANSFER,Savings,2026-01-02 09:00:00,2026-01-02 09:00:00,"
        "Saving vault deposit prefunding wallet,10.00,0.00,EUR,COMPLETED,60.00\n"
        "CARD_CREDIT,Savings,2026-01-03 09:00:00,2026-01-03 09:00:00,"
        "Interest earned - Travel,0.02,0.00,EUR,COMPLETED,60.02\n"
        "TRANSFER,Current,2026-01-04 09:00:00,2026-01-04 09:00:00,"
        "From Flexible Cash Funds,20.00,0.00,EUR,COMPLETED,70.00\n"
    )
    path = tmp_path / "revolut_legacy.csv"
    path.write_text(content, encoding="utf-8")

    statement = revolut.parse_current(path, "Main", None)
    assert statement.rows[0].pocket == "Flexible Cash Funds"
    assert statement.rows[0].pocket_side is False
    assert statement.rows[1].pocket == "Flexible Cash Funds"
    assert statement.rows[1].pocket_side is True
    assert statement.rows[2].pocket is None
    assert statement.rows[2].pocket_side is True
    assert statement.rows[3].pocket == "Travel"
    assert statement.rows[3].pocket_side is True
    assert statement.rows[4].pocket == "Flexible Cash Funds"
    assert statement.rows[4].pocket_side is False

    chains = {chain.name: chain.indexes for chain in statement.chains}
    assert set(chains) == {"Current", "Savings"}
    assert check_balances(statement) == ()


def test_current_fund_move_without_matching_pocket_row(tmp_path: Path) -> None:
    content = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "TRANSFER,Current,2026-01-01 09:00:00,2026-01-01 09:00:00,"
        "To EUR Flexible Cash Funds,-50.00,0.00,EUR,COMPLETED,50.00\n"
    )
    path = tmp_path / "revolut_fund_only.csv"
    path.write_text(content, encoding="utf-8")

    statement = revolut.parse_current(path, "Main", None)
    row = statement.rows[0]
    assert row.pocket == "Flexible Cash Funds"
    assert row.counterparty is None


def test_current_legacy_transfer_spelling_counterparty(tmp_path: Path) -> None:
    content = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "TRANSFER,Current,2026-01-01 09:00:00,2026-01-01 09:00:00,"
        "Transfer to Revolut user,-5.00,0.00,EUR,COMPLETED,95.00\n"
    )
    path = tmp_path / "revolut_legacy_transfer.csv"
    path.write_text(content, encoding="utf-8")

    statement = revolut.parse_current(path, "Main", None)
    row = statement.rows[0]
    assert row.pocket is None
    assert row.counterparty == "Revolut user"


def test_current_wrong_header_raises() -> None:
    with pytest.raises(StatementFormatError) as exc:
        revolut.parse_current(FIXTURES / "revolut_savings.csv", "Main", None)
    assert exc.value.row == 1
    assert exc.value.column == "header"


def test_current_bad_amount_cell_raises(tmp_path: Path) -> None:
    content = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "Card Payment,Current,2026-08-01 10:00:00,2026-08-01 12:00:00,Coffee Corner,"
        "abc,0.00,EUR,COMPLETED,96.50\n"
    )
    path = tmp_path / "revolut_bad_amount.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(StatementFormatError) as exc:
        revolut.parse_current(path, "Main", None)
    assert exc.value.row == 2


def test_savings_row_count_and_bank_types() -> None:
    statement = revolut.parse_savings(FIXTURES / "revolut_savings.csv", "Savings", None)
    assert statement.kind == "savings"
    assert len(statement.rows) == 6
    assert [row.bank_type for row in statement.rows] == [
        "Service Fee Charged",
        "Return PAID",
        "BUY",
        "SELL",
        "Return Reinvested",
        "Return WITHDRAWN",
    ]
    for row in statement.rows:
        assert isinstance(row.amount, Decimal)
    assert statement.chains == ()


def test_savings_amounts_and_currency() -> None:
    statement = revolut.parse_savings(FIXTURES / "revolut_savings.csv", "Savings", None)
    assert statement.rows[0].amount == Decimal("-0.0072")
    assert str(statement.rows[0].amount) == "-0.0072"
    assert statement.rows[2].amount == Decimal("-200")
    assert all(row.currency == "EUR" for row in statement.rows)


def test_savings_narrow_nbsp_before_meridiem(tmp_path: Path) -> None:
    content = (
        'Date,Description,"Value, EUR",Price per share,Quantity of shares\n'
        '"Sep 27, 2026, 3:24:42\u202fAM",BUY EUR Class R IE000TEST0000,-1.00,1.00,1\n'
    )
    path = tmp_path / "revolut_savings_nbsp.csv"
    path.write_text(content, encoding="utf-8")

    statement = revolut.parse_savings(path, "Savings", None)
    assert statement.rows[0].date == datetime(2026, 9, 27, 3, 24, 42)


def test_savings_unknown_description_keeps_row_with_none_type(tmp_path: Path) -> None:
    content = (
        'Date,Description,"Value, EUR",Price per share,Quantity of shares\n'
        '"Sep 27, 2026, 3:24:42 AM",Something Unrecognised,1.00,,\n'
    )
    path = tmp_path / "revolut_savings_unknown.csv"
    path.write_text(content, encoding="utf-8")

    statement = revolut.parse_savings(path, "Savings", None)
    assert len(statement.rows) == 1
    assert statement.rows[0].bank_type is None


def test_savings_older_interest_kinds_are_recognized(tmp_path: Path) -> None:
    content = (
        'Date,Description,"Value, EUR",Price per share,Quantity of shares\n'
        '"Sep 27, 2026, 3:24:42 AM",Interest PAID,0.02,,\n'
        '"Sep 28, 2026, 3:24:42 AM",Interest WITHDRAWN,-0.02,,\n'
    )
    path = tmp_path / "revolut_savings_old_interest.csv"
    path.write_text(content, encoding="utf-8")

    statement = revolut.parse_savings(path, "Savings", None)
    assert [row.bank_type for row in statement.rows] == ["Interest PAID", "Interest WITHDRAWN"]


def test_savings_wrong_header_raises() -> None:
    with pytest.raises(StatementFormatError) as exc:
        revolut.parse_savings(FIXTURES / "revolut_pockets.csv", "Savings", None)
    assert exc.value.row == 1
    assert exc.value.column == "header"


def test_savings_bad_value_cell_raises(tmp_path: Path) -> None:
    content = (
        'Date,Description,"Value, EUR",Price per share,Quantity of shares\n'
        '"Sep 27, 2026, 3:24:42 AM",BUY EUR Class R IE000TEST0000,abc,1.00,1\n'
    )
    path = tmp_path / "revolut_savings_bad_value.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(StatementFormatError) as exc:
        revolut.parse_savings(path, "Savings", None)
    assert exc.value.row == 2


def test_current_input_rows_counts_non_blank_records_after_header(tmp_path: Path) -> None:
    assert revolut.parse_current(FIXTURES / "revolut_pockets.csv", "Main", None).input_rows == 12
    content = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "Card Payment,Current,2026-08-01 10:00:00,2026-08-01 12:00:00,Coffee,"
        "-3.50,0.00,EUR,COMPLETED,96.50\n"
        "\n"
        ",,,,,,,,,\n"
        "Card Payment,Current,2026-08-02 10:00:00,2026-08-02 12:00:00,Tea,"
        "-1.50,0.00,EUR,COMPLETED,95.00\n"
    )
    path = tmp_path / "revolut_blank.csv"
    path.write_text(content, encoding="utf-8")

    assert revolut.parse_current(path, "Main", None).input_rows == 2


def test_savings_input_rows_counts_records() -> None:
    statement = revolut.parse_savings(FIXTURES / "revolut_savings.csv", "Savings", None)
    assert statement.input_rows == 6


def test_rows_carry_the_account_kind() -> None:
    current = revolut.parse_current(FIXTURES / "revolut_pockets.csv", "Main", None)
    savings = revolut.parse_savings(FIXTURES / "revolut_savings.csv", "Savings", None)
    assert {row.kind for row in current.rows} == {"current"}
    assert {row.kind for row in savings.rows} == {"savings"}


def test_current_line_is_the_physical_line(tmp_path: Path) -> None:
    content = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "Card Payment,Current,2026-08-01 10:00:00,2026-08-01 12:00:00,Coffee,"
        "-3.50,0.00,EUR,COMPLETED,96.50\n"
        "\n"
        "Card Payment,Current,2026-08-02 10:00:00,2026-08-02 12:00:00,Tea,"
        "-1.50,0.00,EUR,COMPLETED,95.00\n"
    )
    path = tmp_path / "revolut_blank_line.csv"
    path.write_text(content, encoding="utf-8")

    statement = revolut.parse_current(path, "Main", None)
    assert [row.line for row in statement.rows] == [2, 4]


def test_current_pocket_prefix_is_stripped_only_for_a_file_currency(tmp_path: Path) -> None:
    content = (
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "Transfer,Current,2026-08-01 10:00:00,2026-08-01 10:00:00,"
        "To NYC Trip,-5.00,0.00,EUR,COMPLETED,95.00\n"
        "Transfer,Deposit,2026-08-01 10:00:00,2026-08-01 10:00:00,"
        "To NYC Trip,5.00,0.00,EUR,COMPLETED,5.00\n"
        "Transfer,Current,2026-08-02 10:00:00,2026-08-02 10:00:00,"
        "To EUR Travel,-1.00,0.00,EUR,COMPLETED,94.00\n"
        "Transfer,Deposit,2026-08-02 10:00:00,2026-08-02 10:00:00,"
        "To EUR Travel,1.00,0.00,EUR,COMPLETED,6.00\n"
    )
    path = tmp_path / "revolut_nyc.csv"
    path.write_text(content, encoding="utf-8")

    statement = revolut.parse_current(path, "Main", None)
    assert [row.pocket for row in statement.rows] == ["NYC Trip", "NYC Trip", "Travel", "Travel"]
