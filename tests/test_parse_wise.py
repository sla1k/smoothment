from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.statement.balance import check_balances
from smoothment.statement.model import StatementFormatError
from smoothment.statement.parsers import wise
from tests.conftest import FIXTURES


def test_current_row_count_and_line_numbers() -> None:
    statement = wise.parse_current(FIXTURES / "wise.csv", "Main", None)
    assert statement.bank == "wise"
    assert statement.kind == "current"
    assert len(statement.rows) == 4
    assert [row.line for row in statement.rows] == [2, 3, 4, 5]
    for row in statement.rows:
        assert isinstance(row.amount, Decimal)


def test_current_external_ids_and_bank_types() -> None:
    statement = wise.parse_current(FIXTURES / "wise.csv", "Main", None)
    assert [row.external_id for row in statement.rows] == [
        "TRANSFER-300000003",
        "CARD-300000002",
        "BALANCE_CASHBACK-300000001",
        "TRANSFER-300000000",
    ]
    assert [row.bank_type for row in statement.rows] == [
        "TRANSFER",
        "CARD",
        "CASHBACK",
        "DEPOSIT",
    ]


def test_current_second_row_amount_and_date() -> None:
    statement = wise.parse_current(FIXTURES / "wise.csv", "Main", None)
    row = statement.rows[1]
    assert row.amount == Decimal("-2.70")
    assert row.date == datetime(2026, 9, 5, 10, 7, 33, 409000)
    assert row.has_time is True


def test_current_counterparties() -> None:
    statement = wise.parse_current(FIXTURES / "wise.csv", "Main", None)
    assert [row.counterparty for row in statement.rows] == [
        "Sample Owner",
        "Sample Cafe ISTANBUL",
        None,
        "Sample Owner",
    ]


def test_current_counterparty_account() -> None:
    statement = wise.parse_current(FIXTURES / "wise.csv", "Main", None)
    assert statement.rows[0].counterparty_account == "ES1234567890123456789012"
    assert statement.rows[1].counterparty_account is None


def test_current_reference() -> None:
    statement = wise.parse_current(FIXTURES / "wise.csv", "Main", None)
    assert statement.rows[3].reference == "Top-up"
    assert statement.rows[0].reference is None


def test_current_all_rows_settled() -> None:
    statement = wise.parse_current(FIXTURES / "wise.csv", "Main", None)
    assert all(row.state == "settled" for row in statement.rows)


def test_current_chain_and_balances_check_out() -> None:
    statement = wise.parse_current(FIXTURES / "wise.csv", "Main", None)
    assert len(statement.chains) == 1
    chain = statement.chains[0]
    assert chain.name == "EUR"
    assert chain.indexes == (3, 2, 1, 0)
    assert check_balances(statement) == ()


def test_current_wrong_header_raises(tmp_path: Path) -> None:
    content = "TransferWise ID,Date Time,Amount\nTRANSFER-1,22-09-2026 00:09:17.281,-42.00\n"
    path = tmp_path / "wise_bad_header.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(StatementFormatError) as exc:
        wise.parse_current(path, "Main", None)
    assert exc.value.row == 1
    assert exc.value.column == "header"
    assert "Running Balance" in str(exc.value)


def test_current_bad_amount_cell_raises(tmp_path: Path) -> None:
    header = (
        '"TransferWise ID",Date,"Date Time",Amount,Currency,Description,"Payment Reference",'
        '"Running Balance","Exchange From","Exchange To","Exchange Rate","Payer Name",'
        '"Payee Name","Payee Account Number",Merchant,"Card Last Four Digits",'
        '"Card Holder Full Name",Attachment,Note,"Total fees","Exchange To Amount",'
        '"Transaction Type","Transaction Details Type"\n'
    )
    row = (
        "TRANSFER-300000003,22-09-2026,22-09-2026 00:09:17.281,abc,EUR,"
        "Sent money to Sample Owner,,0.17,,,,,Sample Owner,"
        "ES12 3456 7890 1234 5678 9012,,,,,,0.00,,DEBIT,TRANSFER\n"
    )
    path = tmp_path / "wise_bad_amount.csv"
    path.write_text(header + row, encoding="utf-8")

    with pytest.raises(StatementFormatError) as exc:
        wise.parse_current(path, "Main", None)
    assert exc.value.row == 2
    assert exc.value.column == "Amount"


def test_current_row_with_extra_column_raises(tmp_path: Path) -> None:
    header = (
        '"TransferWise ID",Date,"Date Time",Amount,Currency,Description,"Payment Reference",'
        '"Running Balance","Exchange From","Exchange To","Exchange Rate","Payer Name",'
        '"Payee Name","Payee Account Number",Merchant,"Card Last Four Digits",'
        '"Card Holder Full Name",Attachment,Note,"Total fees","Exchange To Amount",'
        '"Transaction Type","Transaction Details Type"\n'
    )
    row = (
        "TRANSFER-300000003,22-09-2026,22-09-2026 00:09:17.281,-42.00,EUR,"
        "Sent money to Sample Owner,,0.17,,,,,Sample Owner,"
        "ES12 3456 7890 1234 5678 9012,,,,,,0.00,,DEBIT,TRANSFER,EXTRA\n"
    )
    path = tmp_path / "wise_extra_column.csv"
    path.write_text(header + row, encoding="utf-8")

    with pytest.raises(StatementFormatError) as exc:
        wise.parse_current(path, "Main", None)
    assert exc.value.row == 2
    assert exc.value.column == "row"


def test_current_row_missing_last_column_raises(tmp_path: Path) -> None:
    header = (
        '"TransferWise ID",Date,"Date Time",Amount,Currency,Description,"Payment Reference",'
        '"Running Balance","Exchange From","Exchange To","Exchange Rate","Payer Name",'
        '"Payee Name","Payee Account Number",Merchant,"Card Last Four Digits",'
        '"Card Holder Full Name",Attachment,Note,"Total fees","Exchange To Amount",'
        '"Transaction Type","Transaction Details Type"\n'
    )
    row = (
        "TRANSFER-300000003,22-09-2026,22-09-2026 00:09:17.281,-42.00,EUR,"
        "Sent money to Sample Owner,,0.17,,,,,Sample Owner,"
        "ES12 3456 7890 1234 5678 9012,,,,,,0.00,,DEBIT\n"
    )
    path = tmp_path / "wise_missing_column.csv"
    path.write_text(header + row, encoding="utf-8")

    with pytest.raises(StatementFormatError) as exc:
        wise.parse_current(path, "Main", None)
    assert exc.value.row == 2
    assert exc.value.column == "row"


def test_current_input_rows_counts_non_blank_records() -> None:
    statement = wise.parse_current(FIXTURES / "wise.csv", "Main", None)
    assert statement.input_rows == 4


def test_current_input_rows_ignores_blank_records(tmp_path: Path) -> None:
    lines = (FIXTURES / "wise.csv").read_text(encoding="utf-8").splitlines()
    blank = "," * lines[0].count(",")
    path = tmp_path / "wise_blank.csv"
    path.write_text("\n".join([lines[0], lines[1], blank, lines[2]]) + "\n", encoding="utf-8")

    statement = wise.parse_current(path, "Main", None)
    assert statement.input_rows == 2
    assert len(statement.rows) == 2


def test_current_counterparty_follows_direction_when_both_names_are_present(
    tmp_path: Path,
) -> None:
    header = (FIXTURES / "wise.csv").read_text(encoding="utf-8").splitlines()[0]
    outgoing = (
        "TRANSFER-1,22-09-2026,22-09-2026 00:09:17.281,-42.00,EUR,Sent money,,10.00,,,,"
        "Payer Person,Payee Person,,,,,,,0.00,,DEBIT,TRANSFER"
    )
    incoming = (
        "TRANSFER-2,23-09-2026,23-09-2026 00:09:17.281,42.00,EUR,Received money,,52.00,,,,"
        "Payer Person,Payee Person,,,,,,,0.00,,CREDIT,DEPOSIT"
    )
    path = tmp_path / "wise_both_names.csv"
    path.write_text("\n".join([header, outgoing, incoming]) + "\n", encoding="utf-8")

    statement = wise.parse_current(path, "Main", None)

    assert [row.counterparty for row in statement.rows] == ["Payee Person", "Payer Person"]
