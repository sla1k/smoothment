import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from smoothment.classify.model import ClassifiedRow
from smoothment.config import TransferSettings
from smoothment.export import lump_tag, memo_tag
from smoothment.link import Transfer
from smoothment.lumps import Lump
from smoothment.moneywiz.model import MoneyWizSnapshot, Transaction

LUMP_MARKER = re.compile(r"(?<![\w-])smt-lump:([0-9a-f]{8}):(\d{8}T\d{6})(?!\w)")
_CUTOFF_FORMAT = "%Y%m%dT%H%M%S"
_DEFAULT_WINDOW_DAYS = 1
_TRANSFER_KINDS = frozenset({"transfer_in", "transfer_out"})


@dataclass(frozen=True, slots=True)
class PlainUnit:
    row: ClassifiedRow

    def tags(self, tags: Mapping[int, str]) -> tuple[str, ...]:
        return (_row_tag(self.row, tags),)


@dataclass(frozen=True, slots=True)
class TransferUnit:
    transfer: Transfer

    def tags(self, tags: Mapping[int, str]) -> tuple[str, ...]:
        return tuple(_row_tag(leg, tags) for _, leg in _present_legs(self.transfer))


@dataclass(frozen=True, slots=True)
class LumpUnit:
    lump: Lump

    def tags(self, tags: Mapping[int, str]) -> tuple[str, ...]:
        return (lump_tag(self.lump),)


type Unit = PlainUnit | TransferUnit | LumpUnit


@dataclass(frozen=True, slots=True)
class Match:
    unit: Unit
    transaction: Transaction
    how: Literal["tag", "fuzzy"]
    leg: ClassifiedRow | None  # the statement leg that matched, for a transfer
    other: Transaction | None = None  # the row of the other leg when the match is not linked


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    matches: tuple[Match, ...]
    remaining: tuple[Unit, ...]
    consumed: frozenset[int]  # MoneyWiz pks used, including the linked leg of a transfer


type _RowKey = tuple[datetime, str, int, Decimal, str, str, str]
type _UnitKey = tuple[datetime, str, int, tuple[_RowKey, ...]]


@dataclass(frozen=True, slots=True)
class _Leg:
    row: ClassifiedRow
    account: str
    counterpart: str | None  # transfer legs only: the account the other side must be in
    is_transfer_leg: bool


@dataclass(frozen=True, slots=True)
class _Slot:
    unit_index: int
    unit_key: _UnitKey
    leg: _Leg
    account_pk: int
    counterpart_pk: int | None
    day: date

    @property
    def order(self) -> tuple[date, _UnitKey, _RowKey]:
        return (self.day, self.unit_key, _row_key(self.leg.row))


@dataclass(frozen=True, slots=True)
class _Phase:
    slot_ok: Callable[[_Slot], bool]
    transaction_ok: Callable[[Transaction], bool]
    window: Callable[[_Slot, Transaction], int | None]  # None: this slot may not take it


def _row_tag(classified: ClassifiedRow, tags: Mapping[int, str]) -> str:
    return tags.get(id(classified.row)) or memo_tag(classified.row)


def _present_legs(transfer: Transfer) -> tuple[tuple[Literal["out", "in"], ClassifiedRow], ...]:
    legs: list[tuple[Literal["out", "in"], ClassifiedRow]] = []
    if transfer.outgoing is not None:
        legs.append(("out", transfer.outgoing))
    if transfer.incoming is not None:
        legs.append(("in", transfer.incoming))
    return tuple(legs)


def _row_key(classified: ClassifiedRow) -> _RowKey:
    r = classified.row
    return (r.date, r.account, r.line, r.amount, r.description, r.bank, r.external_id or "")


def _unit_key(unit: Unit) -> _UnitKey:
    match unit:
        case PlainUnit(row):
            key = _row_key(row)
            return (key[0], key[1], 0, (key,))
        case TransferUnit(transfer):
            keys = tuple(sorted(_row_key(leg) for _, leg in _present_legs(transfer)))
            return (keys[0][0], keys[0][1], 1, keys)
        case LumpUnit(lump):
            keys = tuple(sorted(_row_key(row) for row in lump.rows))
            return (lump.cutoff, lump.account, 2, keys)


def _plain_account(classified: ClassifiedRow) -> str:
    return classified.account or classified.row.account


def _legs(unit: Unit) -> tuple[_Leg, ...]:
    match unit:
        case PlainUnit(row):
            return (_Leg(row, _plain_account(row), None, False),)
        case TransferUnit(transfer):
            legs: list[_Leg] = []
            if transfer.outgoing is not None:
                legs.append(_Leg(transfer.outgoing, transfer.source, transfer.destination, True))
            if transfer.incoming is not None:
                legs.append(_Leg(transfer.incoming, transfer.destination, transfer.source, True))
            return tuple(legs)
        case LumpUnit():
            return ()


def lump_cutoffs(snapshot: MoneyWizSnapshot) -> dict[str, datetime]:
    """The newest `smt-lump:` cutoff found in MoneyWiz notes, per lump key."""
    cutoffs: dict[str, datetime] = {}
    for transaction in snapshot.transactions:
        for key, text in LUMP_MARKER.findall(transaction.notes):
            try:
                cutoff = datetime.strptime(text, _CUTOFF_FORMAT)
            except ValueError:
                continue
            if key not in cutoffs or cutoff > cutoffs[key]:
                cutoffs[key] = cutoff
    return cutoffs


def _is_linked(transaction: Transaction) -> bool:
    return transaction.kind in _TRANSFER_KINDS and transaction.linked_pk is not None


def _consume(consumed: set[int], unit: Unit, transaction: Transaction) -> None:
    """Take a MoneyWiz row; a transfer or lump also takes the linked row of the other side."""
    consumed.add(transaction.pk)
    if not isinstance(unit, PlainUnit) and _is_linked(transaction):
        assert transaction.linked_pk is not None
        consumed.add(transaction.linked_pk)


def _tag_leg(unit: Unit, transaction: Transaction, tags: Mapping[int, str]) -> ClassifiedRow | None:
    if not isinstance(unit, TransferUnit):
        return None
    held = set(transaction.tags)
    hits = [
        (side, leg) for side, leg in _present_legs(unit.transfer) if _row_tag(leg, tags) in held
    ]
    if not hits:
        return None
    if len(hits) == 2:
        incoming = transaction.kind == "transfer_in" or (
            transaction.kind not in _TRANSFER_KINDS and transaction.amount > 0
        )
        wanted = "in" if incoming else "out"
        return next(leg for side, leg in hits if side == wanted)
    return hits[0][1]


def _tag_pass(
    ordered: Sequence[Unit],
    tags: Mapping[int, str],
    snapshot: MoneyWizSnapshot,
    consumed: set[int],
) -> dict[int, Match]:
    by_tag: dict[str, list[Transaction]] = defaultdict(list)
    for transaction in sorted(snapshot.transactions, key=lambda t: t.pk):
        for tag in transaction.tags:
            by_tag[tag].append(transaction)

    matches: dict[int, Match] = {}
    for index, unit in enumerate(ordered):
        found = next(
            (
                transaction
                for tag in unit.tags(tags)
                for transaction in by_tag.get(tag, ())
                if transaction.pk not in consumed
            ),
            None,
        )
        if found is None:
            continue
        _consume(consumed, unit, found)
        leg = _tag_leg(unit, found, tags)
        matches[index] = Match(unit, _own_side(unit, leg, found, snapshot), "tag", leg)
    return matches


def _own_side(
    unit: Unit, leg: ClassifiedRow | None, found: Transaction, snapshot: MoneyWizSnapshot
) -> Transaction:
    """MoneyWiz copies the notes to both legs of a transfer; report the one in the leg's account."""
    if not isinstance(unit, TransferUnit) or leg is None or found.linked_pk is None:
        return found
    name = unit.transfer.source if leg is unit.transfer.outgoing else unit.transfer.destination
    account = snapshot.account(name)
    linked = snapshot.by_pk(found.linked_pk)
    if account is None or linked is None or found.account_pk == account.pk:
        return found
    return linked if linked.account_pk == account.pk else found


def _distance(slot: _Slot, transaction: Transaction) -> int:
    return abs((slot.day - transaction.date.date()).days)


def _phases(settings: TransferSettings) -> tuple[_Phase, ...]:
    wide = max(settings.window_days, _DEFAULT_WINDOW_DAYS)

    def transfer_window(slot: _Slot, transaction: Transaction) -> int | None:
        if slot.counterpart_pk is None or transaction.other_account_pk != slot.counterpart_pk:
            return None
        return wide

    def narrow(slot: _Slot, transaction: Transaction) -> int | None:
        return _DEFAULT_WINDOW_DAYS

    return (
        _Phase(
            slot_ok=lambda slot: slot.leg.is_transfer_leg,
            transaction_ok=lambda t: t.kind in _TRANSFER_KINDS,
            window=transfer_window,
        ),
        _Phase(
            slot_ok=lambda slot: not slot.leg.is_transfer_leg,
            transaction_ok=lambda t: t.kind not in _TRANSFER_KINDS,
            window=narrow,
        ),
        _Phase(slot_ok=lambda slot: True, transaction_ok=lambda t: True, window=narrow),
    )


def _build_slots(
    ordered: Sequence[Unit], open_indexes: Sequence[int], snapshot: MoneyWizSnapshot
) -> list[_Slot]:
    resolved: dict[str, int | None] = {}

    def pk_of(name: str) -> int | None:
        if name not in resolved:
            found = snapshot.account(name)
            resolved[name] = found.pk if found is not None else None
        return resolved[name]

    slots: list[_Slot] = []
    for index in open_indexes:
        unit = ordered[index]
        unit_key = _unit_key(unit)
        for leg in _legs(unit):
            account_pk = pk_of(leg.account)
            if account_pk is None:
                continue
            counterpart_pk = pk_of(leg.counterpart) if leg.counterpart is not None else None
            slots.append(
                _Slot(index, unit_key, leg, account_pk, counterpart_pk, leg.row.row.date.date())
            )
    return slots


def _sweep(
    phase: _Phase,
    ordered: Sequence[Unit],
    slots: Sequence[_Slot],
    walk: Sequence[Transaction],
    consumed: set[int],
    matched: dict[int, Match],
) -> None:
    """Walk MoneyWiz rows by date; each goes to the open statement leg whose window ends first.

    Serving the earliest deadline first gives the largest matching: a leg passed over now
    could still take a later row, while the leg chosen could not.
    """
    slots_by_group: dict[tuple[int, Decimal], list[_Slot]] = defaultdict(list)
    for slot in slots:
        if phase.slot_ok(slot):
            slots_by_group[(slot.account_pk, slot.leg.row.row.amount)].append(slot)

    def deadline(slot: _Slot, transaction: Transaction) -> date | None:
        window = phase.window(slot, transaction)
        if window is None or _distance(slot, transaction) > window:
            return None
        return slot.day + timedelta(days=window)

    for transaction in walk:
        if transaction.pk in consumed or not phase.transaction_ok(transaction):
            continue
        offers = [
            (due, _distance(slot, transaction), slot.order, slot)
            for slot in slots_by_group.get((transaction.account_pk, transaction.amount), ())
            if slot.unit_index not in matched and (due := deadline(slot, transaction)) is not None
        ]
        if not offers:
            continue
        chosen = min(offers, key=lambda offer: offer[:3])[3]
        unit = ordered[chosen.unit_index]
        _consume(consumed, unit, transaction)
        leg = chosen.leg.row if chosen.leg.is_transfer_leg else None
        matched[chosen.unit_index] = Match(unit, transaction, "fuzzy", leg)


def _other_leg(unit: TransferUnit, matched_leg: ClassifiedRow) -> _Leg | None:
    for leg in _legs(unit):
        if leg.row is not matched_leg:
            return leg
    return None


def _second_legs(
    matched: dict[int, Match],
    snapshot: MoneyWizSnapshot,
    tags: Mapping[int, str],
    consumed: set[int],
) -> None:
    """A transfer found as one plain row also owns the row of its other leg."""
    for index in sorted(matched):
        match = matched[index]
        if (
            not isinstance(match.unit, TransferUnit)
            or match.leg is None
            or _is_linked(match.transaction)
        ):
            continue
        other = _other_leg(match.unit, match.leg)
        found = snapshot.account(other.account) if other is not None else None
        if other is None or found is None:
            continue
        other_tag = _row_tag(other.row, tags)
        day = other.row.row.date.date()
        candidates = [
            t
            for t in snapshot.transactions
            if t.pk not in consumed
            and t.kind != "reconcile"
            and t.account_pk == found.pk
            and t.amount == other.row.row.amount
            and abs((day - t.date.date()).days) <= _DEFAULT_WINDOW_DAYS
            and (not t.tags or other_tag in t.tags)
        ]
        if not candidates:
            continue
        chosen = min(
            candidates,
            key=lambda t: (other_tag not in t.tags, abs((day - t.date.date()).days), t.date, t.pk),
        )
        _consume(consumed, match.unit, chosen)
        matched[index] = replace(match, other=chosen)


def reconcile(
    units: Sequence[Unit],
    tags: Mapping[int, str],
    snapshot: MoneyWizSnapshot,
    settings: TransferSettings,
) -> ReconcileResult:
    """Decide which export units MoneyWiz already holds: by tag first, then by amount and date."""
    ordered = sorted(units, key=_unit_key)
    consumed: set[int] = set()

    matched = _tag_pass(ordered, tags, snapshot, consumed)

    open_indexes = [i for i in range(len(ordered)) if i not in matched]
    slots = _build_slots(ordered, open_indexes, snapshot)
    walk = sorted(
        (
            t
            for t in snapshot.transactions
            if t.kind != "reconcile" and not t.tags and t.pk not in consumed
        ),
        key=lambda t: (t.date.date(), t.pk),
    )
    for phase in _phases(settings):
        _sweep(phase, ordered, slots, walk, consumed, matched)

    _second_legs(matched, snapshot, tags, consumed)

    return ReconcileResult(
        matches=tuple(matched[i] for i in sorted(matched)),
        remaining=tuple(unit for i, unit in enumerate(ordered) if i not in matched),
        consumed=frozenset(consumed),
    )
