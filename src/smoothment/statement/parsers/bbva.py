from pathlib import Path

from smoothment.statement.model import (
    ParsedStatement,
    StatementFormatError,
    StatementRow,
    parse_cell,
    single_chain,
)
from smoothment.statement.sheets import cell_date, cell_decimal, has_content, xlsx_rows

BANK = "bbva"

HEADER_ROW = 5

ENGLISH = (
    "Eff. Date",
    "Date",
    "Item",
    "Transaction",
    "Amount",
    "Foreign currency",
    "Available",
    "Foreign currency",
    "Comments",
)
SPANISH = (
    "F.Valor",
    "Fecha",
    "Concepto",
    "Movimiento",
    "Importe",
    "Divisa",
    "Disponible",
    "Divisa",
    "Observaciones",
)

_DATE_FORMATS: dict[tuple[object, ...], str] = {
    ENGLISH: "%m/%d/%Y",
    SPANISH: "%d/%m/%Y",
}

_CARD_PAYMENT = {"card payment", "pago con tarjeta"}


def header_of(sheet: list[tuple[object, ...]]) -> tuple[object, ...]:
    if len(sheet) < HEADER_ROW:
        return ()
    return tuple(sheet[HEADER_ROW - 1][1:10])


def parse_current(path: Path, account: str, identity: str | None) -> ParsedStatement:
    sheet = xlsx_rows(path)
    header = header_of(sheet)
    date_format = _DATE_FORMATS.get(header)
    if date_format is None:
        raise StatementFormatError(
            file=path,
            row=HEADER_ROW,
            column="header",
            expected=f"{ENGLISH} or {SPANISH}",
            found=str(header),
        )

    rows: list[StatementRow] = []
    for line, sheet_row in enumerate(sheet[HEADER_ROW:], start=HEADER_ROW + 1):
        cells = sheet_row[1:10]
        if all(cell is None for cell in cells):
            continue

        eff_date = cells[0]
        item = cells[2]
        transaction = cells[3]
        amount_cell = cells[4]
        currency_cell = cells[5]
        available = cells[6]
        comments = cells[8]

        date = parse_cell(
            eff_date,
            lambda value: cell_date(value, date_format),
            file=path,
            row=line,
            column=str(header[0]),
            expected=f"date matching {date_format!r}",
        )
        amount = parse_cell(
            amount_cell,
            cell_decimal,
            file=path,
            row=line,
            column=str(header[4]),
            expected="decimal",
        )
        balance = parse_cell(
            available, cell_decimal, file=path, row=line, column=str(header[6]), expected="decimal"
        )

        currency = str(currency_cell).strip() if currency_cell not in (None, "") else "EUR"
        description = str(item) if item is not None else ""
        bank_type = str(transaction) if transaction is not None else None
        reference = str(comments) if comments is not None else None
        counterparty = (
            description
            if bank_type is not None and bank_type.strip().casefold() in _CARD_PAYMENT
            else None
        )

        rows.append(
            StatementRow(
                bank=BANK,
                account=account,
                line=line,
                date=date,
                has_time=False,
                amount=amount,
                currency=currency,
                description=description,
                kind="current",
                counterparty=counterparty,
                reference=reference,
                bank_type=bank_type,
                balance=balance,
            )
        )

    chains = single_chain(rows[0].currency, rows, newest_first_on_tie=True) if rows else ()

    return ParsedStatement(
        file=path,
        bank=BANK,
        kind="current",
        account=account,
        rows=tuple(rows),
        input_rows=sum(1 for sheet_row in sheet[HEADER_ROW:] if has_content(sheet_row[1:10])),
        chains=chains,
    )
