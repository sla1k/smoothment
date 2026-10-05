from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from smoothment.classify.model import ClassifiedRow
from smoothment.config import Config
from smoothment.convert import ConvertResult, FileResult, run_convert
from smoothment.link import Transfer
from smoothment.lumps import Lump
from smoothment.moneywiz.model import MoneyWizSnapshot, Transaction, normalize_text
from smoothment.reconcile import (
    LUMP_MARKER,
    LumpUnit,
    Match,
    PlainUnit,
    TransferUnit,
    Unit,
    reconcile,
)
from smoothment.statement.model import BalanceChain, ParsedStatement, StatementRow

NO_BALANCE = "no balance in the statement"
HIDDEN = "hidden"
_TRANSFER_KINDS = frozenset({"transfer_in", "transfer_out"})


@dataclass(frozen=True, slots=True)
class Posting:
    account: str
    day: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class MissingItem:
    unit: Unit
    day: date
    account: str
    amount: Decimal
    description: str
    postings: tuple[Posting, ...]  # what MoneyWiz would hold per account once imported


@dataclass(frozen=True, slots=True)
class WrongItem:
    day: date
    account: str
    amount: Decimal
    description: str
    problem: str


@dataclass(frozen=True, slots=True)
class ExtraItem:
    transaction: Transaction

    @property
    def day(self) -> date:
        return self.transaction.date.date()

    @property
    def account(self) -> str:
        return self.transaction.account

    @property
    def amount(self) -> Decimal:
        return self.transaction.amount

    @property
    def description(self) -> str:
        parts = [self.transaction.payee or "", self.transaction.description]
        return " / ".join(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class BalanceEntry:
    file: Path
    account: str
    chain: str | None
    day: date | None
    statement: Decimal | None
    moneywiz: Decimal | None
    pending: Decimal
    missing: Decimal
    extra: Decimal
    note: str | None = None

    @property
    def difference(self) -> Decimal | None:
        """MoneyWiz minus the statement; None when either side is unknown."""
        if self.statement is None or self.moneywiz is None:
            return None
        return self.moneywiz - self.statement

    @property
    def unexplained(self) -> Decimal | None:
        """What is left of the difference after pending, extra and missing rows."""
        if self.difference is None:
            return None
        return self.difference - (self.pending + self.extra - self.missing)

    @property
    def pending_explains(self) -> bool:
        """The statement's pending rows alone account for the whole difference."""
        return self.difference is not None and self.difference == self.pending

    @property
    def agrees(self) -> bool:
        """No difference, or one explained by pending rows alone or with missing and extra rows.

        Pending rows alone are enough: an extra MoneyWiz row the bank booked before the
        statement began is extra to the statement without moving the difference.
        """
        return self.difference in (None, 0) or self.pending_explains or self.unexplained == 0


@dataclass(frozen=True, slots=True)
class InconsistentStatement:
    file: Path
    problem: str


@dataclass(frozen=True, slots=True)
class VerifyResult:
    missing: tuple[MissingItem, ...]
    wrong: tuple[WrongItem, ...]
    extra: tuple[ExtraItem, ...]
    balances: tuple[BalanceEntry, ...]
    inconsistent: tuple[InconsistentStatement, ...] = ()

    @property
    def disagreeing(self) -> tuple[BalanceEntry, ...]:
        return tuple(entry for entry in self.balances if not entry.agrees)

    @property
    def clean(self) -> bool:
        return not (
            self.missing or self.wrong or self.extra or self.inconsistent or self.disagreeing
        )


def _key(name: str) -> str:
    return normalize_text(name).casefold()


def _account(classified: ClassifiedRow) -> str:
    return classified.account or classified.row.account


def _units(result: ConvertResult) -> tuple[Unit, ...]:
    in_transfer = {
        id(leg)
        for transfer in result.transfers
        for leg in (transfer.outgoing, transfer.incoming)
        if leg is not None
    }
    units: list[Unit] = [
        PlainUnit(row)
        for file in result.files
        for row in file.exported
        if id(row) not in in_transfer
    ]
    units.extend(TransferUnit(transfer) for transfer in result.transfers)
    units.extend(LumpUnit(lump) for lump in result.lumps)
    return tuple(units)


def _transfer_postings(transfer: Transfer) -> tuple[Posting, ...]:
    outgoing, incoming = transfer.outgoing, transfer.incoming
    if outgoing is None:
        assert incoming is not None
        sent_day, sent = incoming.row.date.date(), -incoming.row.amount
    else:
        sent_day, sent = outgoing.row.date.date(), outgoing.row.amount
    if incoming is None:
        received_day, received = sent_day, -sent
    else:
        received_day, received = incoming.row.date.date(), incoming.row.amount
    return (
        Posting(transfer.source, sent_day, sent),
        Posting(transfer.destination, received_day, received),
    )


def _is_roundup_transfer(lump: Lump) -> bool:
    return lump.kind == "roundups" and lump.counterpart is not None


def _lump_postings(lump: Lump) -> tuple[Posting, ...]:
    own = Posting(lump.account, lump.date, lump.amount)
    if _is_roundup_transfer(lump):
        assert lump.counterpart is not None
        return (own, Posting(lump.counterpart, lump.date, -lump.amount))
    return (own,)


def _lump_accounts(lump: Lump) -> str:
    if not _is_roundup_transfer(lump):
        return lump.account
    if lump.amount < 0:
        return f"{lump.account} -> {lump.counterpart}"
    return f"{lump.counterpart} -> {lump.account}"


def _missing_item(unit: Unit) -> MissingItem:
    match unit:
        case PlainUnit(row):
            return MissingItem(
                unit=unit,
                day=row.row.date.date(),
                account=_account(row),
                amount=row.row.amount,
                description=row.row.description,
                postings=(Posting(_account(row), row.row.date.date(), row.row.amount),),
            )
        case TransferUnit(transfer):
            legs = [leg for leg in (transfer.outgoing, transfer.incoming) if leg is not None]
            primary = legs[0]
            return MissingItem(
                unit=unit,
                day=min(leg.row.date for leg in legs).date(),
                account=f"{transfer.source} -> {transfer.destination}",
                amount=primary.row.amount,
                description=primary.row.description,
                postings=_transfer_postings(transfer),
            )
        case LumpUnit(lump):
            noun = "row" if len(lump.rows) == 1 else "rows"
            return MissingItem(
                unit=unit,
                day=lump.date,
                account=_lump_accounts(lump),
                amount=lump.amount,
                description=(
                    f"{lump.kind} lump of {len(lump.rows)} {noun}, "
                    f"{lump.first.isoformat()} to {lump.date.isoformat()}"
                ),
                postings=_lump_postings(lump),
            )


def _expected_counterpart(match: Match, transfer: Transfer) -> str:
    transaction = match.transaction
    if match.leg is not None:
        return transfer.destination if match.leg is transfer.outgoing else transfer.source
    return transfer.destination if transaction.kind == "transfer_out" else transfer.source


def _incoming_row(transaction: Transaction, snapshot: MoneyWizSnapshot) -> Transaction | None:
    if transaction.kind == "transfer_in":
        return transaction
    if transaction.linked_pk is None:
        return None
    linked = snapshot.by_pk(transaction.linked_pk)
    return linked if linked is not None and linked.kind == "transfer_in" else None


def _wrong_item(transaction: Transaction, problem: str, leg: ClassifiedRow) -> WrongItem:
    return WrongItem(
        day=transaction.date.date(),
        account=transaction.account,
        amount=transaction.amount,
        description=leg.row.description,
        problem=problem,
    )


def wrong_transfers(matches: Sequence[Match], snapshot: MoneyWizSnapshot) -> tuple[WrongItem, ...]:
    items: list[WrongItem] = []
    for match in matches:
        if not isinstance(match.unit, TransferUnit):
            continue
        transfer = match.unit.transfer
        transaction = match.transaction
        leg = match.leg or transfer.outgoing or transfer.incoming
        assert leg is not None
        between = f"{transfer.source} and {transfer.destination}"
        if transaction.kind not in _TRANSFER_KINDS:
            items.append(
                _wrong_item(
                    transaction,
                    f"imported as a plain row; expected a transfer between {between}",
                    leg,
                )
            )
            continue
        expected = _expected_counterpart(match, transfer)
        expected_account = snapshot.account(expected)
        if expected_account is None or transaction.other_account_pk != expected_account.pk:
            found = transaction.other_account or "no account"
            items.append(
                _wrong_item(transaction, f"transfer goes to {found}; expected {expected}", leg)
            )
            continue
        outgoing, incoming = transfer.outgoing, transfer.incoming
        if outgoing is None or incoming is None:
            continue
        if outgoing.row.currency == incoming.row.currency:
            continue
        received = _incoming_row(transaction, snapshot)
        if received is not None and received.amount != incoming.row.amount:
            items.append(
                _wrong_item(
                    received,
                    f"set the received amount to {incoming.row.amount} {incoming.row.currency} "
                    f"(MoneyWiz has {received.amount})",
                    incoming,
                )
            )
    return tuple(items)


def _statement_range(statement: ParsedStatement) -> tuple[date, date] | None:
    """The days on which a MoneyWiz row with no statement row counts as extra.

    A statement starts partway through its first day, so MoneyWiz rows of that day may
    predate it; the first day is left out.
    """
    if not statement.rows:
        return None
    days = [row.date.date() for row in statement.rows]
    first, last = min(days) + timedelta(days=1), max(days)
    return (first, last) if first <= last else None


def _pocket_accounts(statement: ParsedStatement, config: Config) -> list[str]:
    mapping = config.pockets.accounts.get(statement.account, {})
    used = {row.pocket for row in statement.rows if row.pocket is not None}
    return [target for pocket, target in mapping.items() if pocket in used and target != HIDDEN]


def _extra(
    files: Sequence[FileResult],
    matches: Sequence[Match],
    consumed: frozenset[int],
    snapshot: MoneyWizSnapshot,
    config: Config,
) -> tuple[ExtraItem, ...]:
    claimed = set(consumed)
    for match in matches:
        claimed.add(match.transaction.pk)
        if match.other is not None:
            claimed.add(match.other.pk)
    for transaction in snapshot.transactions:
        if LUMP_MARKER.search(transaction.notes):
            claimed.add(transaction.pk)
            if transaction.linked_pk is not None:
                claimed.add(transaction.linked_pk)

    found: dict[int, Transaction] = {}
    for file in files:
        statement = file.statement
        span = _statement_range(statement)
        if span is None:
            continue
        for account in [statement.account, *_pocket_accounts(statement, config)]:
            for transaction in snapshot.transactions_in(account, *span):
                if transaction.pk not in claimed and transaction.kind != "reconcile":
                    found[transaction.pk] = transaction
    ordered = sorted(found.values(), key=lambda t: (t.date, t.account, t.pk))
    return tuple(ExtraItem(t) for t in ordered)


def _chain_rows(statement: ParsedStatement, chain: BalanceChain) -> list[StatementRow]:
    return [statement.rows[index] for index in chain.indexes]


def _chain_account(
    statement: ParsedStatement, rows: Sequence[StatementRow], config: Config
) -> str | None:
    """The MoneyWiz account a chain belongs to; None for a hidden or unmapped pocket."""
    if not all(row.pocket_side for row in rows):
        return statement.account
    mapping = config.pockets.accounts.get(statement.account, {})
    targets = {mapping.get(row.pocket or "", HIDDEN) for row in rows}
    if len(targets) != 1 or HIDDEN in targets:
        return None
    return next(iter(targets))


def _pending_sum(statement: ParsedStatement, rows: Sequence[StatementRow], day: date) -> Decimal:
    pocket_side = all(row.pocket_side for row in rows)
    pockets = {row.pocket for row in rows}
    return sum(
        (
            row.amount
            for row in statement.rows
            if row.state == "pending"
            and row.date.date() <= day
            and row.pocket_side == pocket_side
            and (not pocket_side or row.pocket in pockets)
        ),
        Decimal(0),
    )


def _sum_until(postings: Sequence[Posting], account: str, day: date) -> Decimal:
    wanted = _key(account)
    return sum(
        (p.amount for p in postings if p.day <= day and _key(p.account) == wanted),
        Decimal(0),
    )


def _balances(
    files: Sequence[FileResult],
    missing: Sequence[MissingItem],
    extra: Sequence[ExtraItem],
    snapshot: MoneyWizSnapshot,
    config: Config,
) -> tuple[BalanceEntry, ...]:
    missing_postings = [p for item in missing for p in item.postings]
    extra_postings = [Posting(item.account, item.day, item.amount) for item in extra]

    entries: list[BalanceEntry] = []
    for file in files:
        statement = file.statement
        compared = False
        for chain in statement.chains:
            rows = _chain_rows(statement, chain)
            if not rows:
                continue
            account = _chain_account(statement, rows, config)
            compared = True
            if account is None:
                continue
            last = rows[-1]
            assert last.balance is not None
            day = last.date.date()
            entries.append(
                BalanceEntry(
                    file=statement.file,
                    account=account,
                    chain=chain.name,
                    day=day,
                    statement=last.balance,
                    moneywiz=snapshot.balance(account, day),
                    pending=_pending_sum(statement, rows, day),
                    missing=_sum_until(missing_postings, account, day),
                    extra=_sum_until(extra_postings, account, day),
                )
            )
        if not compared:
            entries.append(
                BalanceEntry(
                    file=statement.file,
                    account=statement.account,
                    chain=None,
                    day=None,
                    statement=None,
                    moneywiz=None,
                    pending=Decimal(0),
                    missing=Decimal(0),
                    extra=Decimal(0),
                    note=NO_BALANCE,
                )
            )
    return tuple(entries)


def _inconsistent(files: Sequence[FileResult]) -> tuple[InconsistentStatement, ...]:
    found: list[InconsistentStatement] = []
    for file in files:
        name = file.statement.file
        if file.mismatches:
            rows = "row" if len(file.mismatches) == 1 else "rows"
            found.append(
                InconsistentStatement(
                    name, f"running balance does not add up on {len(file.mismatches)} {rows}"
                )
            )
        accounting = file.accounting
        if not accounting.balanced:
            found.append(
                InconsistentStatement(
                    name,
                    f"row accounting: {accounting.source_rows} input rows, "
                    f"{accounting.accounted} accounted",
                )
            )
    return tuple(found)


def run_verify(folder: Path, config: Config, snapshot: MoneyWizSnapshot) -> VerifyResult:
    """Compare a folder of statements with what MoneyWiz holds after the import.

    The statements are converted against the same store, so rows an earlier lump covers are
    left out exactly as `convert` leaves them out.
    """
    converted = run_convert(folder, config, dry_run=True, snapshot=snapshot, check_accounts=False)
    outcome = reconcile(_units(converted), converted.tags, snapshot, config.transfers)
    missing = tuple(_missing_item(unit) for unit in outcome.remaining)
    missing = tuple(sorted(missing, key=lambda item: (item.day, item.account, item.amount)))
    wrong = wrong_transfers(outcome.matches, snapshot)
    extra = _extra(converted.files, outcome.matches, outcome.consumed, snapshot, config)
    balances = _balances(converted.files, missing, extra, snapshot, config)
    return VerifyResult(
        missing=missing,
        wrong=wrong,
        extra=extra,
        balances=balances,
        inconsistent=_inconsistent(converted.files),
    )
