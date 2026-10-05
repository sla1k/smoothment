import re
from datetime import datetime
from pathlib import Path

from smoothment.statement.model import (
    ParsedStatement,
    StatementFormatError,
    StatementRow,
    parse_cell,
    single_chain,
)
from smoothment.statement.sheets import cell_date, cell_decimal, has_content, xlsx_rows

BANK = "santander"

TITLE = "CUENTA ONLINE SANTANDER"
TITLE_ROWS = 8

HEADER = ("FECHA OPERACIÓN", "FECHA VALOR", "CONCEPTO", "IMPORTE EUR", "SALDO")

DATE_FORMAT = "%d/%m/%Y"

_IBAN = re.compile(r"ES\d{22}")

_TRANSFER = re.compile(r"^Transferencia (?:Inmediata )?(?:A Favor De|De) (?P<name>[^,]+)")
_PAGO_MOVIL = re.compile(r"^Pago Movil En (?P<name>[^,]+)")
_REFERENCE_MARK = ", Concepto "


def iban(path: Path) -> str | None:
    """Scan the title block for the account's IBAN, returned without spaces."""
    for row in xlsx_rows(path)[:TITLE_ROWS]:
        for cell in row:
            if not isinstance(cell, str):
                continue
            candidate = cell.replace(" ", "")
            if _IBAN.fullmatch(candidate):
                return candidate
    return None


def _evidence(concepto: str) -> tuple[str | None, str | None, str | None]:
    if match := _TRANSFER.match(concepto):
        reference = None
        mark = concepto.find(_REFERENCE_MARK)
        if mark != -1:
            reference = concepto[mark + len(_REFERENCE_MARK) :].strip()
        return match.group("name").strip(), "Transferencia", reference
    if match := _PAGO_MOVIL.match(concepto):
        return match.group("name").strip(), "Pago Movil", None
    return None, None, None


def _parse_date(value: object) -> datetime:
    return cell_date(value, DATE_FORMAT)


def _find_header(sheet: list[tuple[object, ...]]) -> int | None:
    for index, row in enumerate(sheet):
        if tuple(row[:5]) == HEADER:
            return index
    return None


def parse_current(path: Path, account: str, identity: str | None) -> ParsedStatement:
    sheet = xlsx_rows(path)
    header_index = _find_header(sheet)
    if header_index is None:
        raise StatementFormatError(
            file=path, row=0, column="header", expected=str(HEADER), found="not found"
        )

    rows: list[StatementRow] = []
    for line, sheet_row in enumerate(sheet[header_index + 1 :], start=header_index + 2):
        cells = sheet_row[:5]
        if all(cell is None for cell in cells):
            continue

        date_cell, _value_date_cell, concepto_cell, amount_cell, balance_cell = cells

        date = parse_cell(
            date_cell,
            _parse_date,
            file=path,
            row=line,
            column=HEADER[0],
            expected=f"date matching {DATE_FORMAT!r}",
        )
        amount = parse_cell(
            amount_cell, cell_decimal, file=path, row=line, column=HEADER[3], expected="decimal"
        )
        balance = parse_cell(
            balance_cell, cell_decimal, file=path, row=line, column=HEADER[4], expected="decimal"
        )

        concepto = str(concepto_cell) if concepto_cell is not None else ""
        counterparty, bank_type, reference = _evidence(concepto)

        rows.append(
            StatementRow(
                bank=BANK,
                account=account,
                line=line,
                date=date,
                has_time=False,
                amount=amount,
                currency="EUR",
                description=concepto,
                kind="current",
                counterparty=counterparty,
                reference=reference,
                bank_type=bank_type,
                balance=balance,
            )
        )

    chains = single_chain("EUR", rows, newest_first_on_tie=True)

    data_rows = sheet[header_index + 1 :]
    return ParsedStatement(
        file=path,
        bank=BANK,
        kind="current",
        account=account,
        rows=tuple(rows),
        input_rows=sum(1 for sheet_row in data_rows if has_content(sheet_row[:5])),
        chains=chains,
    )
