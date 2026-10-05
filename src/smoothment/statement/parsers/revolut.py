import csv
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from smoothment.money import parse_decimal
from smoothment.statement.model import (
    BalanceChain,
    ParsedStatement,
    RowState,
    StatementFormatError,
    StatementRow,
    file_order,
    parse_cell,
)

BANK = "revolut"

HEADER = [
    "Type",
    "Product",
    "Started Date",
    "Completed Date",
    "Description",
    "Amount",
    "Fee",
    "Currency",
    "State",
    "Balance",
]

CURRENT_SNIFF_PREFIX = HEADER[:3]

CURRENT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
SAVINGS_DATE_FORMAT = "%b %d, %Y, %I:%M:%S %p"

SAVINGS_HEADER_PREFIX = ["Date", "Description"]
SAVINGS_HEADER_SUFFIX = ["Price per share", "Quantity of shares"]
SAVINGS_VALUE_PREFIX = "Value, "

POCKET_EXPORT_HEADER = [
    "Transaction/Value date",
    "Description",
    "AER",
    "NIR",
    "Money in",
    "Money out",
    "Balance",
]

SAVINGS_FUND = "Flexible Cash Funds"
POCKET_MOVE = re.compile(r"^(?:To|From) (?P<name>.+)$")
CURRENCY_PREFIX = re.compile(r"^(?P<currency>[A-Z]{3}) (?P<rest>.+)$")
POCKET_INTEREST = re.compile(
    r'^Net interest paid to "(?P<name>[^"]+)"|^Interest earned - (?P<old>.+)$'
)
COUNTERPARTY = re.compile(r"^(?:Transfer to|Transfer from|Payment from|To|From) (?P<name>.+)$")

_STATE_MAP: dict[str, RowState] = {
    "COMPLETED": "settled",
    "PENDING": "pending",
    "REVERTED": "reverted",
}

SAVINGS_KINDS = (
    "Service Fee Charged",
    "Return Reinvested",
    "Return WITHDRAWN",
    "Return PAID",
    "Interest PAID",
    "Interest WITHDRAWN",
    "BUY",
    "SELL",
)
_SAVINGS_TYPE = re.compile(
    "^(?:"
    + "|".join(re.escape(kind) for kind in sorted(SAVINGS_KINDS, key=len, reverse=True))
    + ")"
)


def _read_rows(path: Path) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Read a CSV file, returning its header and (line, cells) for non-blank data rows.

    The first non-blank record is the header. `line` is the physical line the record ends
    on, so blank lines are skipped without shifting later line numbers.
    """
    header: list[str] | None = None
    data: list[tuple[int, list[str]]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        for raw_row in reader:
            if not any(cell.strip() for cell in raw_row):
                continue
            if header is None:
                header = raw_row
                continue
            data.append((reader.line_num, raw_row))
    return header or [], data


def _savings_date(text: str) -> datetime:
    return datetime.strptime(text.replace("\u202f", " ").replace("\xa0", " "), SAVINGS_DATE_FORMAT)


def _decimal_cell(path: Path, line: int, cell: dict[str, str], column: str) -> Decimal:
    return parse_cell(
        cell[column], parse_decimal, file=path, row=line, column=column, expected="decimal"
    )


def _pocket_move_name(description: str, currencies: set[str]) -> str | None:
    """The pocket named by a "To …"/"From …" move, without a leading file currency code."""
    match = POCKET_MOVE.match(description)
    if not match:
        return None
    name = match.group("name")
    prefixed = CURRENCY_PREFIX.match(name)
    if prefixed and prefixed.group("currency") in currencies:
        return prefixed.group("rest")
    return name


def _pocket_interest_name(description: str) -> str | None:
    match = POCKET_INTEREST.match(description)
    if not match:
        return None
    return match.group("name") or match.group("old")


def parse_current(path: Path, account: str, identity: str | None) -> ParsedStatement:
    header, data = _read_rows(path)
    if header != HEADER:
        raise StatementFormatError(
            file=path, row=1, column="header", expected=str(HEADER), found=str(header)
        )

    cells_by_line: list[tuple[int, dict[str, str]]] = []
    for line, cells in data:
        if len(cells) != len(HEADER):
            raise StatementFormatError(
                file=path,
                row=line,
                column="row",
                expected=f"{len(HEADER)} columns",
                found=f"{len(cells)} columns",
            )
        cells_by_line.append((line, dict(zip(HEADER, cells, strict=True))))

    currencies = {cell["Currency"] for _, cell in cells_by_line}
    known_pockets: set[str] = set()
    for _, cell in cells_by_line:
        if cell["Product"] != "Current":
            name = _pocket_interest_name(cell["Description"]) or _pocket_move_name(
                cell["Description"], currencies
            )
            if name:
                known_pockets.add(name)

    rows: list[StatementRow] = []
    for line, cell in cells_by_line:
        amount = _decimal_cell(path, line, cell, "Amount") - _decimal_cell(path, line, cell, "Fee")

        state_raw = cell["State"]
        state = _STATE_MAP.get(state_raw)
        if state is None:
            raise StatementFormatError(
                file=path,
                row=line,
                column="State",
                expected="COMPLETED, PENDING or REVERTED",
                found=state_raw,
            )

        balance = _decimal_cell(path, line, cell, "Balance") if cell["Balance"].strip() else None
        date = parse_cell(
            cell["Started Date"],
            lambda text: datetime.strptime(text, CURRENT_DATE_FORMAT),
            file=path,
            row=line,
            column="Started Date",
            expected="e.g. '2026-08-01 10:00:00'",
        )

        pocket_side = cell["Product"] != "Current"
        if pocket_side:
            pocket = _pocket_interest_name(cell["Description"]) or _pocket_move_name(
                cell["Description"], currencies
            )
        else:
            name = _pocket_move_name(cell["Description"], currencies)
            pocket = name if name and (name in known_pockets or name == SAVINGS_FUND) else None

        lower_type = cell["Type"].lower().replace("_", " ")
        counterparty = None
        if pocket is None and lower_type in ("transfer", "deposit"):
            match = COUNTERPARTY.match(cell["Description"])
            if match:
                counterparty = match.group("name")

        rows.append(
            StatementRow(
                bank=BANK,
                account=account,
                line=line,
                date=date,
                has_time=True,
                amount=amount,
                currency=cell["Currency"],
                description=cell["Description"],
                kind="current",
                counterparty=counterparty,
                bank_type=cell["Type"],
                bank_product=cell["Product"],
                state=state,
                balance=balance,
                pocket=pocket,
                pocket_side=pocket_side,
            )
        )

    order = file_order(rows, newest_first_on_tie=False)
    products: list[str | None] = []
    for index in order:
        product = rows[index].bank_product
        if product not in products:
            products.append(product)
    chains = tuple(
        BalanceChain(
            name=product,
            indexes=tuple(
                index
                for index in order
                if rows[index].bank_product == product
                and rows[index].state == "settled"
                and rows[index].balance is not None
            ),
        )
        for product in products
        if product is not None
    )

    return ParsedStatement(
        file=path,
        bank=BANK,
        kind="current",
        account=account,
        rows=tuple(rows),
        input_rows=len(data),
        chains=chains,
    )


def parse_savings(path: Path, account: str, identity: str | None) -> ParsedStatement:
    header, data = _read_rows(path)
    if (
        len(header) != 5
        or header[0:2] != SAVINGS_HEADER_PREFIX
        or header[3:5] != SAVINGS_HEADER_SUFFIX
        or not header[2].startswith(SAVINGS_VALUE_PREFIX)
    ):
        expected = [
            *SAVINGS_HEADER_PREFIX,
            f"{SAVINGS_VALUE_PREFIX}<currency>",
            *SAVINGS_HEADER_SUFFIX,
        ]
        raise StatementFormatError(
            file=path, row=1, column="header", expected=str(expected), found=str(header)
        )
    currency = header[2][len(SAVINGS_VALUE_PREFIX) :]

    rows: list[StatementRow] = []
    for line, cells in data:
        if len(cells) != 5:
            raise StatementFormatError(
                file=path,
                row=line,
                column="row",
                expected="5 columns",
                found=f"{len(cells)} columns",
            )
        date_text, description, value_text, _price, _quantity = cells

        date = parse_cell(
            date_text,
            _savings_date,
            file=path,
            row=line,
            column="Date",
            expected="e.g. 'Sep 27, 2026, 3:24:42 AM'",
        )
        amount = parse_cell(
            value_text, parse_decimal, file=path, row=line, column=header[2], expected="decimal"
        )

        match = _SAVINGS_TYPE.match(description)
        bank_type = match.group(0) if match else None

        rows.append(
            StatementRow(
                bank=BANK,
                account=account,
                line=line,
                date=date,
                has_time=True,
                amount=amount,
                currency=currency,
                description=description,
                kind="savings",
                bank_type=bank_type,
            )
        )

    return ParsedStatement(
        file=path,
        bank=BANK,
        kind="savings",
        account=account,
        rows=tuple(rows),
        input_rows=len(data),
    )
