import csv
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from smoothment.classify.model import ClassifiedRow
from smoothment.lumps import Lump, lump_material
from smoothment.statement.model import StatementRow

# No Category column: with one in the file MoneyWiz skips its own step that links payees to
# categories and leaves every row without a category uncategorised.
COLUMNS = ["Date", "Amount", "Payee", "Description", "Account", "Transfers", "Memo"]
OUTPUT_NAME = "moneywiz_import.csv"
UNMATCHED_PAYEE = "Unmatched transfer"

_LUMP_NOUNS = {
    "roundups": ("round-up", "round-ups"),
    "interest": ("interest payment", "interest payments"),
    "fee": ("fee", "fees"),
}


@dataclass(frozen=True, slots=True)
class ExportRow:
    date: date
    amount: Decimal
    payee: str
    description: str
    account: str
    transfers: str
    memo: str


@dataclass(frozen=True, slots=True)
class TransferLeg:
    row: ClassifiedRow
    counterpart: str  # MoneyWiz account on the other side, as spelled in config
    merged: ClassifiedRow | None = None  # the other leg, carried in Memo instead of exported


@dataclass(frozen=True, slots=True)
class ExportPlan:
    plain: tuple[ClassifiedRow, ...] = ()
    transfers: tuple[TransferLeg, ...] = ()
    unmatched: tuple[ClassifiedRow, ...] = ()
    lumps: tuple[Lump, ...] = ()
    tags: Mapping[int, str] = field(default_factory=dict)  # id(StatementRow) -> memo tag


type _SortKey = tuple[str, date, int, datetime, int, str]


@dataclass(frozen=True, slots=True)
class _Pending:
    sort_key: _SortKey
    row: ExportRow


def _tag(material: str, ordinal: int = 0) -> str:
    if ordinal > 0:
        material += f"|{ordinal}"
    digest = hashlib.sha1(material.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"smt:{digest[:12]}"


def _row_material(row: StatementRow) -> str:
    amount = format(row.amount.normalize(), "f")
    key = row.external_id or f"{row.date.isoformat()}|{amount}|{row.description}"
    return f"{row.bank}|{row.account}|{key}"


def memo_tag(row: StatementRow, ordinal: int = 0) -> str:
    return _tag(_row_material(row), ordinal)


def assign_tags(rows: Sequence[StatementRow]) -> dict[int, str]:
    """Tag each row of one file, numbering identical rows in the order given."""
    seen: dict[str, int] = {}
    tags: dict[int, str] = {}
    for row in rows:
        material = _row_material(row)
        ordinal = seen.get(material, 0)
        seen[material] = ordinal + 1
        tags[id(row)] = _tag(material, ordinal)
    return tags


def _cutoff_text(lump: Lump) -> str:
    return lump.cutoff.strftime("%Y%m%dT%H%M%S")


def lump_tag(lump: Lump) -> str:
    material = lump_material(lump.bank, lump.source_account, lump.kind, lump.pocket, lump.account)
    return _tag(f"{material}|{_cutoff_text(lump)}")


def _same_text(left: str, right: str) -> bool:
    return " ".join(left.split()).casefold() == " ".join(right.split()).casefold()


def _default_payee(classified: ClassifiedRow) -> str:
    row = classified.row
    return classified.payee or row.counterparty or row.description


def _row_tag(classified: ClassifiedRow, tags: Mapping[int, str]) -> str:
    return tags.get(id(classified.row)) or memo_tag(classified.row)


def _statement_row(
    classified: ClassifiedRow,
    *,
    payee: str,
    description: str,
    transfers: str,
    memo: str,
) -> _Pending:
    row = classified.row
    account = classified.account or row.account
    day = row.date.date()
    return _Pending(
        sort_key=(account, day, 0, row.date, row.line, ""),
        row=ExportRow(
            date=day,
            amount=row.amount,
            payee=payee,
            description=description,
            account=account,
            transfers=transfers,
            memo=memo,
        ),
    )


def _plain(classified: ClassifiedRow, tags: Mapping[int, str]) -> _Pending:
    payee = _default_payee(classified)
    description = classified.row.description
    return _statement_row(
        classified,
        payee=payee,
        description="" if _same_text(description, payee) else description,
        transfers="",
        memo=_row_tag(classified, tags),
    )


def _transfer(leg: TransferLeg, tags: Mapping[int, str]) -> _Pending:
    memo = _row_tag(leg.row, tags)
    if leg.merged is not None:
        memo = f"{memo} {_row_tag(leg.merged, tags)}"
    return _statement_row(leg.row, payee="", description="", transfers=leg.counterpart, memo=memo)


def _unmatched(classified: ClassifiedRow, tags: Mapping[int, str]) -> _Pending:
    return _statement_row(
        classified,
        payee=UNMATCHED_PAYEE,
        description=classified.row.description,
        transfers="",
        memo=_row_tag(classified, tags),
    )


def _lump(lump: Lump) -> _Pending:
    count = len(lump.rows)
    singular, plural = _LUMP_NOUNS[lump.kind]
    noun = singular if count == 1 else plural
    description = f"{count} {noun}, {lump.first.isoformat()} to {lump.date.isoformat()}"
    is_roundup = lump.kind == "roundups"
    return _Pending(
        sort_key=(
            lump.account,
            lump.date,
            1,
            datetime.min,
            0,
            f"{lump.kind}|{lump.pocket or ''}|{lump.source_account}",
        ),
        row=ExportRow(
            date=lump.date,
            amount=lump.amount,
            payee="" if is_roundup else (lump.payee or ""),
            description=description,
            account=lump.account,
            transfers=(lump.counterpart or "") if is_roundup else "",
            memo=f"{lump_tag(lump)} smt-lump:{lump.key}:{_cutoff_text(lump)}",
        ),
    )


def to_export_rows(plan: ExportPlan) -> tuple[ExportRow, ...]:
    tags = plan.tags
    pending = [
        *(_plain(classified, tags) for classified in plan.plain),
        *(_transfer(leg, tags) for leg in plan.transfers),
        *(_unmatched(classified, tags) for classified in plan.unmatched),
        *(_lump(lump) for lump in plan.lumps),
    ]
    pending.sort(key=lambda item: item.sort_key)
    return tuple(item.row for item in pending)


def write_csv(path: Path, rows: Iterable[ExportRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.date.isoformat(),
                    format(row.amount, "f"),
                    row.payee,
                    row.description,
                    row.account,
                    row.transfers,
                    row.memo,
                ]
            )
