import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from smoothment.classify.model import ClassifiedRow
from smoothment.config import Config

type LumpKind = Literal["roundups", "interest", "fee"]


@dataclass(frozen=True, slots=True)
class Lump:
    kind: LumpKind
    bank: str
    account: str  # MoneyWiz account the lump row is booked in
    source_account: str  # statement account of the merged rows
    key: str
    counterpart: str | None  # roundups only: the pocket's account
    pocket: str | None
    amount: Decimal  # signed, cents
    date: date  # date of the last merged row
    cutoff: datetime  # timestamp of the last merged row
    first: date  # date of the first merged row
    rows: tuple[ClassifiedRow, ...]  # the merged rows
    payee: str | None


def lump_material(
    bank: str, source_account: str, kind: str, pocket: str | None, account: str
) -> str:
    return f"{bank}|{source_account}|{kind}|{pocket or ''}|{account}"


def lump_key(bank: str, source_account: str, kind: str, pocket: str | None, account: str) -> str:
    material = lump_material(bank, source_account, kind, pocket, account)
    return hashlib.sha1(material.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]


def _bank_payee(config: Config, bank: str) -> str | None:
    settings = config.banks.get(bank)
    return settings.payee if settings else None


def _sum_amounts(rows: Sequence[ClassifiedRow]) -> Decimal:
    return sum((cr.row.amount for cr in rows), Decimal("0"))


def _make_lump(
    kind: LumpKind,
    rows: Sequence[ClassifiedRow],
    *,
    account: str,
    counterpart: str | None,
    pocket: str | None,
    payee: str | None,
) -> Lump:
    sorted_rows = tuple(sorted(rows, key=lambda cr: (cr.row.date, cr.row.line)))
    amount = _sum_amounts(sorted_rows).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    last = sorted_rows[-1].row
    bank = sorted_rows[0].row.bank
    source_account = last.account
    return Lump(
        kind=kind,
        bank=bank,
        account=account,
        source_account=source_account,
        key=lump_key(bank, source_account, kind, pocket, account),
        counterpart=counterpart,
        pocket=pocket,
        amount=amount,
        date=last.date.date(),
        cutoff=last.date,
        first=sorted_rows[0].row.date.date(),
        rows=sorted_rows,
        payee=payee,
    )


def _split_covered(
    rows: Sequence[ClassifiedRow],
    key: str,
    covered: Mapping[str, datetime],
) -> tuple[list[ClassifiedRow], list[ClassifiedRow]]:
    cutoff = covered.get(key)
    if cutoff is None:
        return list(rows), []
    skipped = [cr for cr in rows if cr.row.date.replace(microsecond=0) <= cutoff]
    skipped_ids = {id(cr) for cr in skipped}
    fresh = [cr for cr in rows if id(cr) not in skipped_ids]
    return fresh, skipped


def build_lumps(
    statement_rows: Sequence[ClassifiedRow],
    config: Config,
    covered: Mapping[str, datetime] | None = None,
) -> tuple[tuple[Lump, ...], tuple[ClassifiedRow, ...], tuple[ClassifiedRow, ...]]:
    """Fold the round-ups and micro-income of one statement into lumps.

    `covered` maps a lump key to the cutoff of a lump a previous run already booked; rows of
    that key dated at or before the cutoff are returned as covered instead of merged again.
    Every input row ends up in exactly one returned lump's `rows`, in the individual rows or
    in the covered rows; the three sets together are exactly the input.
    """
    covered = covered or {}
    roundup_max = config.pockets.roundup_max

    roundup_groups: dict[tuple[str, str | None], list[ClassifiedRow]] = {}
    pocket_income_groups: dict[tuple[str, str, str | None], list[ClassifiedRow]] = {}
    savings_interest_groups: dict[str, list[ClassifiedRow]] = {}
    savings_fee_groups: dict[str, list[ClassifiedRow]] = {}

    for classified in statement_rows:
        row = classified.row
        if classified.kind == "pocket_move" and abs(row.amount) <= roundup_max:
            roundup_groups.setdefault((row.account, row.pocket), []).append(classified)
        elif classified.kind == "pocket_income":
            account = classified.account if classified.account is not None else row.account
            pocket_income_groups.setdefault((row.account, account, row.pocket), []).append(
                classified
            )
        elif classified.kind == "interest" and row.kind == "savings":
            savings_interest_groups.setdefault(row.account, []).append(classified)
        elif classified.kind == "fee" and row.kind == "savings":
            savings_fee_groups.setdefault(row.account, []).append(classified)

    lumps: list[Lump] = []
    handled_ids: set[int] = set()
    covered_rows: list[ClassifiedRow] = []

    def fold(
        kind: LumpKind,
        rows: Sequence[ClassifiedRow],
        *,
        source_account: str,
        account: str,
        counterpart: str | None,
        pocket: str | None,
        payee: str | None,
    ) -> None:
        key = lump_key(rows[0].row.bank, source_account, kind, pocket, account)
        fresh, skipped = _split_covered(rows, key, covered)
        handled_ids.update(id(cr) for cr in skipped)
        covered_rows.extend(skipped)
        if not fresh or (kind == "roundups" and _sum_amounts(fresh) == 0):
            return  # zero-sum group: rows stay individual
        handled_ids.update(id(cr) for cr in fresh)
        lumps.append(
            _make_lump(
                kind,
                fresh,
                account=account,
                counterpart=counterpart,
                pocket=pocket,
                payee=payee,
            )
        )

    for (account, pocket), rows in roundup_groups.items():
        fold(
            "roundups",
            rows,
            source_account=account,
            account=account,
            counterpart=rows[0].counterpart,
            pocket=pocket,
            payee=None,
        )

    for (source_account, account, pocket), rows in pocket_income_groups.items():
        fold(
            "interest",
            rows,
            source_account=source_account,
            account=account,
            counterpart=None,
            pocket=pocket,
            payee=_bank_payee(config, rows[0].row.bank),
        )

    for account, rows in savings_interest_groups.items():
        fold(
            "interest",
            rows,
            source_account=account,
            account=account,
            counterpart=None,
            pocket=None,
            payee=_bank_payee(config, rows[0].row.bank),
        )

    for account, rows in savings_fee_groups.items():
        fold(
            "fee",
            rows,
            source_account=account,
            account=account,
            counterpart=None,
            pocket=None,
            payee=_bank_payee(config, rows[0].row.bank),
        )

    lumps.sort(key=lambda lump: (lump.account, lump.kind, lump.pocket or "", lump.source_account))

    individual = tuple(cr for cr in statement_rows if id(cr) not in handled_ids)
    in_input_order = {id(cr): index for index, cr in enumerate(statement_rows)}
    covered_rows.sort(key=lambda cr: in_input_order[id(cr)])

    return tuple(lumps), individual, tuple(covered_rows)
