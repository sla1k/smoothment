from datetime import datetime
from decimal import Decimal
from pathlib import Path

from smoothment.money import parse_decimal
from smoothment.statement.model import (
    ParsedStatement,
    SkippedLine,
    StatementFormatError,
    StatementRow,
    parse_cell,
)
from smoothment.statement.sheets import xls_rows

BANK = "sovcombank"

HEADER = [
    "Дата, время операции (МСК)",
    "Сумма операции (руб)",
    "Начислено кешбэка (баллы)",
    "Описание операции",
    "Номер карты/ стикера",
]

DATE_FORMAT = "%d.%m.%Y %H:%M"


def _parse_amount(text: str) -> Decimal:
    return parse_decimal(text, decimal_sep=",", thousands_sep=" ")


def _parse_date(text: str) -> datetime:
    return datetime.strptime(text, DATE_FORMAT)


def _is_amount(text: str) -> bool:
    try:
        _parse_amount(text)
    except ValueError:
        return False
    return True


def _padded(row: list[str]) -> list[str]:
    cells = [cell.strip() for cell in row[:5]]
    while len(cells) < 5:
        cells.append("")
    return cells


def parse_rows(rows: list[list[str]], path: Path, account: str) -> ParsedStatement:
    header = [cell.strip() for cell in rows[0][:5]] if rows else []
    if header != HEADER:
        raise StatementFormatError(
            file=path, row=1, column="header", expected=str(HEADER), found=str(header)
        )

    statement_rows: list[StatementRow] = []
    skipped: list[SkippedLine] = []
    input_rows = 0

    for offset, raw_row in enumerate(rows[1:], start=1):
        line = offset + 1
        date_cell, amount_cell, cashback_cell, description_cell, card_cell = _padded(raw_row)

        non_empty = [
            cell
            for cell in (date_cell, amount_cell, cashback_cell, description_cell, card_cell)
            if cell
        ]
        if not non_empty:
            continue
        input_rows += 1

        if not date_cell and _is_amount(amount_cell):
            raise StatementFormatError(
                file=path,
                row=line,
                column=HEADER[0],
                expected=f"date matching {DATE_FORMAT!r} on a row with an amount",
                found="empty",
            )
        if not date_cell:
            skipped.append(
                SkippedLine(line=line, text=" ".join(non_empty), reason="section header")
            )
            continue

        date = parse_cell(
            date_cell,
            _parse_date,
            file=path,
            row=line,
            column=HEADER[0],
            expected=f"date matching {DATE_FORMAT!r}",
        )
        amount = parse_cell(
            amount_cell, _parse_amount, file=path, row=line, column=HEADER[1], expected="decimal"
        )

        counterparty = (description_cell or None) if card_cell else None
        reference = card_cell or None

        statement_rows.append(
            StatementRow(
                bank=BANK,
                account=account,
                line=line,
                date=date,
                has_time=True,
                amount=amount,
                currency="RUB",
                description=description_cell,
                kind="current",
                counterparty=counterparty,
                reference=reference,
            )
        )

    return ParsedStatement(
        file=path,
        bank=BANK,
        kind="current",
        account=account,
        rows=tuple(statement_rows),
        input_rows=input_rows,
        skipped=tuple(skipped),
    )


def parse_current(path: Path, account: str, identity: str | None) -> ParsedStatement:
    return parse_rows(xls_rows(path), path, account)
