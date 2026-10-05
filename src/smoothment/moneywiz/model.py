import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

type CategoryType = Literal["expense", "income"]
type TransactionKind = Literal[
    "deposit", "withdraw", "refund", "transfer_in", "transfer_out", "reconcile"
]

TAG_PATTERN = re.compile(r"smt:[0-9a-f]{12}")


class MoneyWizStoreError(Exception):
    """The file is missing or is not a MoneyWiz Core Data store."""


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


@dataclass(frozen=True, slots=True)
class Account:
    pk: int
    name: str
    currency: str
    kind: str
    opening_balance: Decimal
    archived: bool


@dataclass(frozen=True, slots=True)
class Category:
    pk: int
    name: str
    path: str
    type: CategoryType


@dataclass(frozen=True, slots=True)
class Payee:
    pk: int
    name: str


@dataclass(frozen=True, slots=True)
class Transaction:
    pk: int
    kind: TransactionKind
    account: str
    account_pk: int
    amount: Decimal
    date: datetime
    description: str
    notes: str
    payee: str | None
    other_account: str | None
    categories: tuple[str, ...]
    created: datetime
    status: int
    other_account_pk: int | None = None
    linked_pk: int | None = None

    @property
    def tags(self) -> tuple[str, ...]:
        return tuple(TAG_PATTERN.findall(self.notes))


@dataclass(frozen=True, slots=True)
class MoneyWizSnapshot:
    accounts: tuple[Account, ...]
    categories: tuple[Category, ...]
    payees: tuple[Payee, ...]
    transactions: tuple[Transaction, ...]
    _by_pk: dict[int, Transaction] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_pk", {t.pk: t for t in self.transactions})

    def _resolve(self, name: str) -> Account | None:
        wanted = normalize_text(name).casefold()
        matches = [a for a in self.accounts if normalize_text(a.name).casefold() == wanted]
        live = [a for a in matches if not a.archived]
        candidates = live or matches
        if len(candidates) > 1:
            state = "live" if live else "archived"
            raise MoneyWizStoreError(f"More than one {state} account is named {name!r}")
        return candidates[0] if candidates else None

    def account(self, name: str) -> Account | None:
        return self._resolve(name)

    def by_pk(self, pk: int) -> Transaction | None:
        return self._by_pk.get(pk)

    def transactions_in(self, account: str, start: date, end: date) -> tuple[Transaction, ...]:
        resolved = self._resolve(account)
        if resolved is None:
            return ()
        return tuple(
            t
            for t in self.transactions
            if t.account_pk == resolved.pk and start <= t.date.date() <= end
        )

    def balance(self, account: str, day: date) -> Decimal | None:
        resolved = self._resolve(account)
        if resolved is None:
            return None
        return resolved.opening_balance + sum(
            (
                t.amount
                for t in self.transactions
                if t.account_pk == resolved.pk and t.date.date() <= day
            ),
            Decimal(0),
        )

    def find_by_memo(self, tag: str) -> tuple[Transaction, ...]:
        return tuple(t for t in self.transactions if tag in t.notes)
