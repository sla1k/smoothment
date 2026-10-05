from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.classify.model import ClassifiedRow
from smoothment.export import ExportPlan, to_export_rows
from smoothment.statement.model import StatementFormatError
from smoothment.statement.parsers import tbank
from tests.conftest import FIXTURES

FIXTURE = FIXTURES / "tbank_two_accounts.ofx"
ACCOUNT_1 = "40817810000000000001"
ACCOUNT_2 = "0500000001"


def test_account_ids_returns_both_in_file_order() -> None:
    assert tbank.account_ids(FIXTURE) == (ACCOUNT_1, ACCOUNT_2)


def test_first_account_row_count_and_line_numbers() -> None:
    statement = tbank.parse_current(FIXTURE, "Main", ACCOUNT_1)
    assert statement.bank == "tbank"
    assert statement.kind == "current"
    assert len(statement.rows) == 2
    assert [row.line for row in statement.rows] == [1, 2]
    for row in statement.rows:
        assert isinstance(row.amount, Decimal)


def test_second_account_row_count_and_description() -> None:
    statement = tbank.parse_current(FIXTURE, "Savings", ACCOUNT_2)
    assert len(statement.rows) == 1
    assert statement.rows[0].description == "Между своими счетами"


def test_first_row_fields() -> None:
    statement = tbank.parse_current(FIXTURE, "Main", ACCOUNT_1)
    row = statement.rows[0]
    assert row.date == datetime(2026, 9, 10, 19, 32, 27)
    assert row.has_time is True
    assert row.amount == Decimal("-7.00")
    assert row.currency == "RUB"
    assert row.counterparty == row.description == "Sample Mobile"
    assert row.bank_category == "Мобильная связь"
    assert row.bank_type == "DEBIT"
    assert row.external_id == "100000000001"


def test_second_row_amount_and_no_category() -> None:
    statement = tbank.parse_current(FIXTURE, "Main", ACCOUNT_1)
    row = statement.rows[1]
    assert row.amount == Decimal("0.53")
    assert row.bank_category is None


def test_unknown_identity_raises_naming_acctid(tmp_path: Path) -> None:
    with pytest.raises(StatementFormatError) as exc:
        tbank.parse_current(FIXTURE, "Main", "does-not-exist")
    assert "ACCTID" in str(exc.value)


def test_malformed_xml_raises_and_account_ids_empty(tmp_path: Path) -> None:
    path = tmp_path / "tbank_malformed.ofx"
    path.write_text("<OFX><BANKMSGSRSV1><STMTTRNRS>", encoding="utf-8")

    assert tbank.account_ids(path) == ()
    with pytest.raises(StatementFormatError) as exc:
        tbank.parse_current(path, "Main", ACCOUNT_1)
    assert "well-formed" in str(exc.value)


def test_transaction_without_name_raises(tmp_path: Path) -> None:
    content = """<?xml version="1.0" encoding="UTF-8"?>
<?OFX OFXHEADER="200" VERSION="211" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>
<OFX>
  <BANKMSGSRSV1>
    <STMTTRNRS>
      <STMTRS>
        <CURDEF>RUB</CURDEF>
        <BANKACCTFROM>
          <BANKID>T-BANK</BANKID>
          <ACCTID>40817810000000000099</ACCTID>
        </BANKACCTFROM>
        <BANKTRANLIST>
          <STMTTRN>
            <TRNTYPE>DEBIT</TRNTYPE>
            <DTPOSTED>20260910193227.000[+3:MSK]</DTPOSTED>
            <TRNAMT>-7</TRNAMT>
            <FITID>1</FITID>
          </STMTTRN>
        </BANKTRANLIST>
      </STMTRS>
    </STMTTRNRS>
  </BANKMSGSRSV1>
</OFX>
"""
    path = tmp_path / "tbank_missing_name.ofx"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(StatementFormatError) as exc:
        tbank.parse_current(path, "Main", "40817810000000000099")
    assert "NAME" in str(exc.value)


def test_input_rows_counts_stmttrn_in_the_selected_block() -> None:
    assert tbank.parse_current(FIXTURE, "Main", ACCOUNT_1).input_rows == 2
    assert tbank.parse_current(FIXTURE, "Savings", ACCOUNT_2).input_rows == 1


def test_account_ids_raises_when_a_block_lacks_acctid(tmp_path: Path) -> None:
    content = FIXTURE.read_text(encoding="utf-8").replace("<ACCTID>0500000001</ACCTID>", "", 1)
    path = tmp_path / "tbank_missing_acctid.ofx"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(StatementFormatError) as exc:
        tbank.account_ids(path)
    assert exc.value.column == "ACCTID"


def test_trnamt_is_parsed_exactly() -> None:
    statement = tbank.parse_current(FIXTURE, "Main", ACCOUNT_1)
    row = statement.rows[1]
    assert str(row.amount) == "0.5300"
    plan = ExportPlan(plain=(ClassifiedRow(row=row, kind="interest", evidence="test"),))
    assert to_export_rows(plan)[0].amount == Decimal("0.53")


def test_cursym_reaches_row_currency(tmp_path: Path) -> None:
    content = FIXTURE.read_text(encoding="utf-8").replace(
        "<FITID>100000000001</FITID>",
        "<FITID>100000000001</FITID>\n<CURRENCY><CURRATE>1.0</CURRATE><CURSYM>USD</CURSYM></CURRENCY>",
    )
    path = tmp_path / "tbank_usd.ofx"
    path.write_text(content, encoding="utf-8")

    statement = tbank.parse_current(path, "Main", ACCOUNT_1)
    assert [row.currency for row in statement.rows] == ["USD", "RUB"]


@pytest.mark.parametrize(
    ("old", "new", "column"),
    [
        (
            "<DTPOSTED>20260910193227.000[+3:MSK]</DTPOSTED>",
            "<DTPOSTED>soon</DTPOSTED>",
            "DTPOSTED",
        ),
        ("<TRNAMT>-7</TRNAMT>", "<TRNAMT>seven</TRNAMT>", "TRNAMT"),
    ],
)
def test_bad_date_or_amount_names_its_own_column(
    tmp_path: Path, old: str, new: str, column: str
) -> None:
    path = tmp_path / "tbank_bad_cell.ofx"
    path.write_text(FIXTURE.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")

    with pytest.raises(StatementFormatError) as exc:
        tbank.parse_current(path, "Main", ACCOUNT_1)
    assert exc.value.row == 1
    assert exc.value.column == column
