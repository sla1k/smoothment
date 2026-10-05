from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from smoothment.config import AccountKind

type RowState = Literal["settled", "pending", "reverted"]


class StatementFormatError(Exception):
    """A statement file doesn't have the shape its parser expects."""

    def __init__(self, file: Path, row: int, column: str, expected: str, found: str) -> None:
        self.file = file
        self.row = row
        self.column = column
        self.expected = expected
        self.found = found
        super().__init__(str(self))

    def __str__(self) -> str:
        return (
            f"{self.file.name} row {self.row}, column {self.column}: "
            f"expected {self.expected}, found {self.found}"
        )


@dataclass(frozen=True, slots=True)
class StatementRow:
    """One transaction as the bank stated it, before any matching or enrichment.

    `account` is the MoneyWiz account name and `kind` the kind of its [[accounts]] entry.
    `line` is the row's position in the source (physical CSV line, sheet row, or the
    STMTTRN's position within its OFX block). `amount` is signed and exact.

    The evidence fields mean different things per bank:

    - Revolut current: `description` is the Description column; `counterparty` is the name
      after "To", "From", "Transfer to/from" or "Payment from" on Transfer/Deposit rows that
      are not pocket moves, else None; `bank_type` is the Type column and `bank_product` the
      Product column; `reference` is None; `balance` is None on pending and reverted rows.
    - Revolut savings: `bank_type` is the leading operation of the Description (BUY, SELL,
      Return PAID, ...), None when unknown; `counterparty`, `reference` and `balance` are None.
    - Wise: `counterparty` is Merchant, else Payee Name on an outflow, else Payer Name on an
      inflow; `counterparty_account` is Payee Account Number without spaces; `reference` is
      Payment Reference; `bank_type` is Transaction Details Type; `external_id` is the
      TransferWise ID; `balance` is Running Balance.
    - TBank: `description` and `counterparty` are both always NAME; `bank_category` is MEMO;
      `bank_type` is TRNTYPE; `external_id` is FITID; `reference` and `balance` are None.
    - BBVA: `description` is the Item/Concepto column; `bank_type` is the Transaction/
      Movimiento column, which on transfers holds free text (e.g. "Sent from revolut") while
      the transfer type ("Transfer received") lives in `description`; `counterparty` is the
      description on card payments only; `reference` is Comments/Observaciones; `balance` is
      Available/Disponible.
    - Santander: `description` is CONCEPTO; `bank_type` is derived from CONCEPTO
      ("Transferencia", "Pago Movil" or None); `counterparty` is the name parsed from
      CONCEPTO; `reference` is the text after ", Concepto " on transfers; `balance` is SALDO.
    - Sovcombank: `description` is the operation description; `counterparty` is that
      description on card rows only (None when it is empty); `reference` is the card/sticker
      number; `bank_type` and `balance` are None.
    """

    bank: str
    account: str
    line: int
    date: datetime
    has_time: bool
    amount: Decimal
    currency: str
    description: str
    kind: AccountKind = "current"
    counterparty: str | None = None
    counterparty_account: str | None = None
    reference: str | None = None
    bank_category: str | None = None
    bank_type: str | None = None
    bank_product: str | None = None
    state: RowState = "settled"
    external_id: str | None = None
    balance: Decimal | None = None
    pocket: str | None = None
    pocket_side: bool = False


@dataclass(frozen=True, slots=True)
class SkippedLine:
    line: int
    text: str
    reason: str


@dataclass(frozen=True, slots=True)
class BalanceChain:
    name: str
    indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    file: Path
    bank: str
    kind: AccountKind
    account: str
    rows: tuple[StatementRow, ...]
    input_rows: int
    skipped: tuple[SkippedLine, ...] = ()
    chains: tuple[BalanceChain, ...] = ()


def file_order(
    rows: Sequence[StatementRow], *, newest_first_on_tie: bool = False
) -> tuple[int, ...]:
    """Indexes in chronological order: reversed when the first row is newer than the last.

    When the first and last rows carry the same date (and time, if any), the dates cannot
    tell the direction; `newest_first_on_tie` states the bank's usual order instead.
    """
    if not rows:
        return ()
    indexes = range(len(rows))
    first, last = rows[0].date, rows[-1].date
    if first > last or (first == last and newest_first_on_tie):
        return tuple(reversed(indexes))
    return tuple(indexes)


def parse_cell[V, T](
    value: V, parse: Callable[[V], T], *, file: Path, row: int, column: str, expected: str
) -> T:
    """Parse one cell, turning a ValueError into a StatementFormatError naming its column."""
    try:
        return parse(value)
    except ValueError as exc:
        raise StatementFormatError(
            file=file, row=row, column=column, expected=expected, found=str(value)
        ) from exc


def single_chain(
    name: str, rows: Sequence[StatementRow], *, newest_first_on_tie: bool
) -> tuple[BalanceChain, ...]:
    """One chain over every row that declares a balance, in chronological order.

    Returns no chain when no row declares a balance.
    """
    indexes = tuple(
        index
        for index in file_order(rows, newest_first_on_tie=newest_first_on_tie)
        if rows[index].balance is not None
    )
    return (BalanceChain(name=name, indexes=indexes),) if indexes else ()
