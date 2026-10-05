from collections.abc import Iterable, Mapping
from datetime import datetime, time
from decimal import Decimal

from smoothment.convert import ConvertResult
from smoothment.export import ExportRow
from smoothment.moneywiz.model import Account, MoneyWizSnapshot, Transaction, TransactionKind
from tests.moneywiz_fixture import FxAccount, FxTransaction

MOMENT = datetime(2026, 9, 1, 12, 0, 0)


def snapshot_of(names: Iterable[str], notes: Iterable[str] = ()) -> MoneyWizSnapshot:
    accounts = tuple(
        Account(
            pk=index,
            name=name,
            currency="EUR",
            kind="bank",
            opening_balance=Decimal(0),
            archived=False,
        )
        for index, name in enumerate(names, start=1)
    )
    transactions = tuple(
        Transaction(
            pk=1000 + index,
            kind="withdraw",
            account=accounts[0].name,
            account_pk=accounts[0].pk,
            amount=Decimal("-1.00"),
            date=MOMENT,
            description="",
            notes=note,
            payee=None,
            other_account=None,
            categories=(),
            created=MOMENT,
            status=2,
        )
        for index, note in enumerate(notes)
    )
    return MoneyWizSnapshot(accounts=accounts, categories=(), payees=(), transactions=transactions)


def exported_names(result: ConvertResult) -> set[str]:
    return {name for row in result.export_rows for name in (row.account, row.transfers) if name}


def _row_moment(row: ExportRow) -> datetime:
    return datetime.combine(row.date, time(1, 0))


def imported_snapshot(
    result: ConvertResult,
    openings: Mapping[str, Decimal] | None = None,
    extra_accounts: Iterable[str] = (),
) -> MoneyWizSnapshot:
    """The store as it looks after MoneyWiz imported every export row of `result`.

    A row with a Transfers value becomes a linked transfer_out/transfer_in pair, the Memo
    sits on the leg of the row's own account. `openings` sets opening balances by account name.
    """
    names = sorted(exported_names(result) | set(extra_accounts))
    openings = openings or {}
    accounts = tuple(
        Account(
            pk=index,
            name=name,
            currency="EUR",
            kind="bank",
            opening_balance=openings.get(name, Decimal(0)),
            archived=False,
        )
        for index, name in enumerate(names, start=1)
    )
    pk_of = {account.name: account.pk for account in accounts}

    def leg(
        row: ExportRow,
        pk: int,
        kind: TransactionKind,
        account: str,
        amount: Decimal,
        notes: str,
        other: str | None = None,
        linked_pk: int | None = None,
    ) -> Transaction:
        return Transaction(
            pk=pk,
            kind=kind,
            account=account,
            account_pk=pk_of[account],
            amount=amount,
            date=_row_moment(row),
            description=row.description,
            notes=notes,
            payee=row.payee or None,
            other_account=other,
            categories=(),
            created=MOMENT,
            status=2,
            other_account_pk=pk_of[other] if other else None,
            linked_pk=linked_pk,
        )

    transactions: list[Transaction] = []
    for index, row in enumerate(result.export_rows):
        pk = 1000 + 2 * index
        if not row.transfers:
            kind: TransactionKind = "deposit" if row.amount > 0 else "withdraw"
            transactions.append(leg(row, pk, kind, row.account, row.amount, row.memo))
            continue
        sent_here = row.amount < 0
        here: TransactionKind = "transfer_out" if sent_here else "transfer_in"
        there: TransactionKind = "transfer_in" if sent_here else "transfer_out"
        transactions.append(
            leg(row, pk, here, row.account, row.amount, row.memo, row.transfers, pk + 1)
        )
        transactions.append(
            leg(row, pk + 1, there, row.transfers, -row.amount, "", row.account, pk)
        )
    return MoneyWizSnapshot(
        accounts=accounts, categories=(), payees=(), transactions=tuple(transactions)
    )


_ENTITY_OF_KIND = {
    "deposit": 38,
    "withdraw": 48,
    "transfer_in": 46,
    "transfer_out": 47,
    "refund": 44,
    "reconcile": 43,
}


def store_rows(snapshot: MoneyWizSnapshot) -> tuple[list[FxAccount], list[FxTransaction]]:
    """The snapshot as rows for `build_db`, to give CLI tests a real store file."""
    accounts = [
        FxAccount(a.pk, a.name, a.currency, opening=float(a.opening_balance))
        for a in snapshot.accounts
    ]
    transactions = [
        FxTransaction(
            t.pk,
            _ENTITY_OF_KIND[t.kind],
            t.account_pk,
            float(t.amount),
            t.date,
            desc=t.description,
            notes=t.notes,
            recipient_account=t.other_account_pk if t.kind == "transfer_out" else None,
            sender_account=t.other_account_pk if t.kind == "transfer_in" else None,
            recipient_transaction=t.linked_pk if t.kind == "transfer_out" else None,
        )
        for t in snapshot.transactions
    ]
    return accounts, transactions
