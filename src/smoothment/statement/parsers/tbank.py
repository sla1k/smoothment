import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from smoothment.money import parse_decimal
from smoothment.statement.model import (
    ParsedStatement,
    StatementFormatError,
    StatementRow,
    parse_cell,
)

BANK = "tbank"
BANK_ID = "T-BANK"

DATE_FORMAT = "%Y%m%d%H%M%S"


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


def _parse_date(text: str) -> datetime:
    return datetime.strptime(text[:14], DATE_FORMAT)


def _parse_amount(text: str) -> Decimal:
    return parse_decimal(text, thousands_sep="")


def _try_parse_root(path: Path) -> ET.Element | None:
    try:
        return ET.parse(path).getroot()
    except ET.ParseError:
        return None


def _stmtrs_blocks(root: ET.Element) -> list[ET.Element]:
    return root.findall(".//STMTRS")


def account_ids(path: Path) -> tuple[str, ...]:
    """The ACCTID of every STMTRS block, in file order; () when the XML does not parse.

    A block without an ACCTID cannot be matched to an account, so it is a format error.
    """
    root = _try_parse_root(path)
    if root is None:
        return ()
    ids: list[str] = []
    for position, stmtrs in enumerate(_stmtrs_blocks(root), start=1):
        acct_id = _text(stmtrs.find("BANKACCTFROM/ACCTID"))
        if acct_id is None:
            raise StatementFormatError(
                file=path,
                row=0,
                column="ACCTID",
                expected="an ACCTID in every STMTRS block",
                found=f"none in block {position}",
            )
        ids.append(acct_id)
    return tuple(ids)


def parse_current(path: Path, account: str, identity: str | None) -> ParsedStatement:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise StatementFormatError(
            file=path, row=0, column="xml", expected="well-formed OFX XML", found=str(exc)
        ) from exc

    matches = [
        stmtrs
        for stmtrs in _stmtrs_blocks(root)
        if _text(stmtrs.find("BANKACCTFROM/ACCTID")) == identity
    ]
    if len(matches) != 1:
        raise StatementFormatError(
            file=path,
            row=0,
            column="ACCTID",
            expected="exactly one STMTRS with matching ACCTID",
            found=f"{len(matches)} matches for {identity!r}",
        )
    stmtrs = matches[0]

    curdef = _text(stmtrs.find("CURDEF")) or ""

    rows: list[StatementRow] = []
    for line, txn in enumerate(stmtrs.findall("BANKTRANLIST/STMTTRN"), start=1):
        bank_type = _text(txn.find("TRNTYPE"))

        date = parse_cell(
            _text(txn.find("DTPOSTED")) or "",
            _parse_date,
            file=path,
            row=line,
            column="DTPOSTED",
            expected="e.g. '20260910193227.000[+3:MSK]'",
        )
        amount = parse_cell(
            _text(txn.find("TRNAMT")) or "",
            _parse_amount,
            file=path,
            row=line,
            column="TRNAMT",
            expected="decimal",
        )

        name = _text(txn.find("NAME"))
        if name is None:
            raise StatementFormatError(
                file=path, row=line, column="NAME", expected="NAME element", found="missing"
            )

        memo = _text(txn.find("MEMO"))
        currency = _text(txn.find("CURRENCY/CURSYM")) or curdef
        fitid = _text(txn.find("FITID"))

        rows.append(
            StatementRow(
                bank=BANK,
                account=account,
                line=line,
                date=date,
                has_time=True,
                amount=amount,
                currency=currency,
                description=name,
                kind="current",
                counterparty=name,
                bank_category=memo,
                bank_type=bank_type,
                external_id=fitid,
            )
        )

    return ParsedStatement(
        file=path,
        bank=BANK,
        kind="current",
        account=account,
        rows=tuple(rows),
        input_rows=sum(1 for _ in stmtrs.iter("STMTTRN")),
    )
