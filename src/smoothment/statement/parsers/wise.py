import csv
from datetime import datetime
from pathlib import Path

from smoothment.money import parse_decimal
from smoothment.statement.model import (
    ParsedStatement,
    StatementFormatError,
    StatementRow,
    parse_cell,
    single_chain,
)

BANK = "wise"

FIRST_COLUMN = "TransferWise ID"

REQUIRED: tuple[str, ...] = (
    FIRST_COLUMN,
    "Date Time",
    "Amount",
    "Currency",
    "Description",
    "Payment Reference",
    "Running Balance",
    "Payer Name",
    "Payee Name",
    "Payee Account Number",
    "Merchant",
    "Total fees",
    "Transaction Type",
    "Transaction Details Type",
)

DATE_FORMAT = "%d-%m-%Y %H:%M:%S.%f"


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_date(text: str) -> datetime:
    return datetime.strptime(text, DATE_FORMAT)


def parse_current(path: Path, account: str, identity: str | None) -> ParsedStatement:
    rows: list[StatementRow] = []
    input_rows = 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        missing = [column for column in REQUIRED if column not in fieldnames]
        if missing:
            raise StatementFormatError(
                file=path,
                row=1,
                column="header",
                expected=f"columns including {', '.join(REQUIRED)}",
                found=f"missing {', '.join(missing)}",
            )

        for record in reader:
            line = reader.line_num
            extra = record.get(None)
            wrong_columns = [key for key in fieldnames if record.get(key) is None]
            if extra or wrong_columns:
                found_count = len(fieldnames) + (len(extra) if extra else 0) - len(wrong_columns)
                raise StatementFormatError(
                    file=path,
                    row=line,
                    column="row",
                    expected=f"{len(fieldnames)} columns",
                    found=f"{found_count} columns",
                )

            if not any(_clean(value) for value in record.values()):
                continue
            input_rows += 1

            amount = parse_cell(
                _clean(record.get("Amount")),
                parse_decimal,
                file=path,
                row=line,
                column="Amount",
                expected="decimal",
            )
            date = parse_cell(
                _clean(record.get("Date Time")),
                _parse_date,
                file=path,
                row=line,
                column="Date Time",
                expected="e.g. '25-08-2026 18:04:20.198'",
            )
            balance_text = _clean(record.get("Running Balance"))
            balance = (
                parse_cell(
                    balance_text,
                    parse_decimal,
                    file=path,
                    row=line,
                    column="Running Balance",
                    expected="decimal",
                )
                if balance_text
                else None
            )

            merchant = _clean(record.get("Merchant"))
            if merchant:
                counterparty = merchant
            elif amount < 0:
                counterparty = _clean(record.get("Payee Name")) or None
            elif amount > 0:
                counterparty = _clean(record.get("Payer Name")) or None
            else:
                counterparty = None

            counterparty_account = (
                _clean(record.get("Payee Account Number")).replace(" ", "") or None
            )
            reference = _clean(record.get("Payment Reference")) or None
            bank_type = _clean(record.get("Transaction Details Type")) or None
            external_id = _clean(record.get(FIRST_COLUMN)) or None

            rows.append(
                StatementRow(
                    bank=BANK,
                    account=account,
                    line=line,
                    date=date,
                    has_time=True,
                    amount=amount,
                    currency=_clean(record.get("Currency")),
                    description=_clean(record.get("Description")),
                    kind="current",
                    counterparty=counterparty,
                    counterparty_account=counterparty_account,
                    reference=reference,
                    bank_type=bank_type,
                    external_id=external_id,
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
        input_rows=input_rows,
        chains=chains,
    )
