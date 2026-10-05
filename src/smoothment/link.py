from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import combinations

from smoothment.classify.model import ClassifiedRow
from smoothment.config import TransferSettings

_SINGLE_LEG_KINDS = frozenset({"pocket_move", "cash"})

# A date-only leg could have happened at any time that day; ranking assumes the middle of it,
# so a timed pair less than 12 hours apart beats a date-only pair on the same day.
_UNKNOWN_TIME_OF_DAY = timedelta(hours=12)


@dataclass(frozen=True, slots=True)
class Transfer:
    outgoing: ClassifiedRow | None  # the negative leg, when a statement holds it
    incoming: ClassifiedRow | None  # the positive leg, when a statement holds it
    source: str  # MoneyWiz account the money leaves
    destination: str  # MoneyWiz account the money reaches
    note: str  # why: "paired 00:12:00 apart", "single leg: only possible counterpart", ...


@dataclass(frozen=True, slots=True)
class LinkResult:
    transfers: tuple[Transfer, ...]
    unmatched: tuple[ClassifiedRow, ...]  # own_transfer candidates with no partner
    notes: tuple[str, ...]  # ties, suspicious gaps


type _ContentKey = tuple[str, datetime, int, Decimal, str]


def _content_key(row: ClassifiedRow) -> _ContentKey:
    """A key from the row's own data, stable regardless of its position in the input."""
    r = row.row
    return (r.account, r.date, r.line, r.amount, r.description)


def _describe(row: ClassifiedRow) -> str:
    r = row.row
    return f"{r.account} {r.date.isoformat()} {r.amount}"


@dataclass(frozen=True, slots=True)
class _Pair:
    out_index: int
    in_index: int
    cross_currency: bool
    gap: timedelta
    effective_gap: timedelta
    full_time: bool
    amount_gap: Decimal
    out_key: _ContentKey
    in_key: _ContentKey

    @property
    def sort_key(self) -> tuple[bool, timedelta, Decimal, _ContentKey, _ContentKey]:
        return (self.cross_currency, self.effective_gap, self.amount_gap, self.out_key, self.in_key)

    @property
    def rank(self) -> tuple[bool, timedelta, Decimal]:
        return (self.cross_currency, self.effective_gap, self.amount_gap)


def _gap(a: ClassifiedRow, b: ClassifiedRow) -> tuple[timedelta, timedelta, bool]:
    """The measured gap, the gap used for ranking, and whether both legs carry a time."""
    if a.row.has_time and b.row.has_time:
        gap = abs(a.row.date - b.row.date)
        return gap, gap, True
    gap = timedelta(days=abs((a.row.date.date() - b.row.date.date()).days))
    return gap, gap + _UNKNOWN_TIME_OF_DAY, False


def _format_gap(gap: timedelta, *, full_time: bool) -> str:
    if not full_time:
        days = gap.days
        unit = "day" if days == 1 else "days"
        return f"{days} {unit}"
    total_seconds = int(gap.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _feasible(a: ClassifiedRow, b: ClassifiedRow, settings: TransferSettings) -> bool:
    if (a.row.amount < 0) == (b.row.amount < 0):
        return False
    if a.row.account == b.row.account:
        return False
    if a.allowed is not None and b.row.account not in a.allowed:
        return False
    if b.allowed is not None and a.row.account not in b.allowed:
        return False
    days_apart = abs((a.row.date.date() - b.row.date.date()).days)
    if days_apart > settings.window_days:
        return False
    if a.row.currency != b.row.currency:
        return a.allowed is not None and b.allowed is not None
    amount_a, amount_b = abs(a.row.amount), abs(b.row.amount)
    tolerance = settings.tolerance * max(amount_a, amount_b)
    return abs(amount_a - amount_b) <= tolerance


def _pair_note(out_row: ClassifiedRow, in_row: ClassifiedRow, gap_text: str) -> str:
    out_amount, in_amount = abs(out_row.row.amount), abs(in_row.row.amount)
    if out_row.row.currency != in_row.row.currency:
        return (
            f"paired {gap_text} apart, {out_amount} {out_row.row.currency} "
            f"against {in_amount} {in_row.row.currency}"
        )
    if out_amount != in_amount:
        return (
            f"paired {gap_text} apart, {out_amount} against {in_amount} "
            f"(difference {abs(out_amount - in_amount)})"
        )
    return f"paired {gap_text} apart"


def _build_pairs(
    candidates: list[tuple[int, ClassifiedRow]], settings: TransferSettings
) -> list[_Pair]:
    pairs: list[_Pair] = []
    for (i, a), (j, b) in combinations(candidates, 2):
        if not _feasible(a, b, settings):
            continue
        gap, effective_gap, full_time = _gap(a, b)
        amount_gap = abs(abs(a.row.amount) - abs(b.row.amount))
        if a.row.amount < 0:
            out_index, in_index, out_row, in_row = i, j, a, b
        else:
            out_index, in_index, out_row, in_row = j, i, b, a
        pairs.append(
            _Pair(
                out_index,
                in_index,
                a.row.currency != b.row.currency,
                gap,
                effective_gap,
                full_time,
                amount_gap,
                _content_key(out_row),
                _content_key(in_row),
            )
        )
    return pairs


def _tie_notes(candidates: list[tuple[int, ClassifiedRow]], pairs: list[_Pair]) -> list[str]:
    index_to_row = dict(candidates)
    partners_by_row: dict[int, list[_Pair]] = defaultdict(list)
    for pair in pairs:
        partners_by_row[pair.out_index].append(pair)
        partners_by_row[pair.in_index].append(pair)

    notes: list[str] = []
    for index, row in candidates:
        partners = partners_by_row.get(index)
        if partners is None or len(partners) < 2:
            continue
        ranked = sorted(partners, key=lambda p: p.sort_key)
        top, second = ranked[0], ranked[1]
        if top.rank != second.rank:
            continue
        other_top = index_to_row[top.in_index if top.out_index == index else top.out_index]
        other_second = index_to_row[
            second.in_index if second.out_index == index else second.out_index
        ]
        gap_text = _format_gap(top.gap, full_time=top.full_time)
        notes.append(
            f"tie linking {_describe(row)}: {_describe(other_top)} and "
            f"{_describe(other_second)} both {gap_text} apart, amount gap {top.amount_gap}"
        )
    return notes


def _single_leg(row: ClassifiedRow, account: str, note: str) -> Transfer:
    if row.row.amount < 0:
        return Transfer(
            outgoing=row, incoming=None, source=row.row.account, destination=account, note=note
        )
    return Transfer(
        outgoing=None, incoming=row, source=account, destination=row.row.account, note=note
    )


def _primary_leg(transfer: Transfer) -> ClassifiedRow:
    if transfer.outgoing is not None and transfer.incoming is not None:
        return (
            transfer.outgoing
            if transfer.outgoing.row.date <= transfer.incoming.row.date
            else transfer.incoming
        )
    leg = transfer.outgoing if transfer.outgoing is not None else transfer.incoming
    assert leg is not None
    return leg


def _optional_content_key(row: ClassifiedRow | None) -> _ContentKey | tuple[()]:
    return _content_key(row) if row is not None else ()


def _transfer_sort_key(
    transfer: Transfer,
) -> tuple[datetime, str, _ContentKey | tuple[()], _ContentKey | tuple[()]]:
    primary = _primary_leg(transfer)
    return (
        primary.row.date,
        primary.row.account,
        _optional_content_key(transfer.outgoing),
        _optional_content_key(transfer.incoming),
    )


def link(rows: Sequence[ClassifiedRow], settings: TransferSettings) -> LinkResult:
    candidates = [(i, row) for i, row in enumerate(rows) if row.kind == "own_transfer"]
    pairs = _build_pairs(candidates, settings)
    notes = _tie_notes(candidates, pairs)

    used: set[int] = set()
    transfers: list[Transfer] = []
    for pair in sorted(pairs, key=lambda p: p.sort_key):
        if pair.out_index in used or pair.in_index in used:
            continue
        used.add(pair.out_index)
        used.add(pair.in_index)
        out_row, in_row = rows[pair.out_index], rows[pair.in_index]
        gap_text = _format_gap(pair.gap, full_time=pair.full_time)
        transfers.append(
            Transfer(
                outgoing=out_row,
                incoming=in_row,
                source=out_row.row.account,
                destination=in_row.row.account,
                note=_pair_note(out_row, in_row, gap_text),
            )
        )

    unmatched: list[ClassifiedRow] = []
    for index, row in candidates:
        if index in used:
            continue
        if not row.pair_only and row.allowed is not None and len(row.allowed) == 1:
            account = next(iter(row.allowed))
            transfers.append(_single_leg(row, account, "single leg: only possible counterpart"))
            notes.append(f"counterpart not found in {account} for {_describe(row)}")
        else:
            unmatched.append(row)

    for row in rows:
        if row.kind not in _SINGLE_LEG_KINDS:
            continue
        assert row.counterpart is not None
        note = "pocket move" if row.kind == "pocket_move" else "cash"
        transfers.append(_single_leg(row, row.counterpart, note))

    transfers.sort(key=_transfer_sort_key)
    unmatched.sort(key=_content_key)
    notes.sort()

    return LinkResult(transfers=tuple(transfers), unmatched=tuple(unmatched), notes=tuple(notes))
