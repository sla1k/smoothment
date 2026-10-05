from dataclasses import dataclass
from typing import Literal

from smoothment.classify.owner import OwnerMatcher
from smoothment.config import Config
from smoothment.statement.model import StatementRow

type RowKind = Literal[
    "own_transfer",
    "pocket_move",
    "pocket_income",
    "cash",
    "third_party",
    "purchase",
    "refund",
    "fee",
    "interest",
    "cashback",
    "income",
    "excluded",
]


@dataclass(frozen=True, slots=True)
class ClassifiedRow:
    row: StatementRow
    kind: RowKind
    evidence: str  # one sentence: which rule fired and on what text
    payee: str | None = None  # payee decided by classification; None = exporter's default
    account: str | None = None  # MoneyWiz account the row belongs to when not row.account
    counterpart: str | None = None  # known counterpart account (pocket target, cash, id match)
    allowed: frozenset[str] | None = None  # own_transfer only: accounts the other leg may be in
    pair_only: bool = False  # own_transfer only: bank-marker evidence, needs a partner row
    reason: str | None = None  # kind == "excluded" only
    reason_detail: str | None = None  # kind == "excluded" only: which case of the reason applies


@dataclass(frozen=True, slots=True)
class ClassifyContext:
    config: Config
    owner: OwnerMatcher
