import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CD_EPOCH_OFFSET = 978307200

ENTITIES = {
    10: "Account",
    11: "BankChequeAccount",
    12: "BankSavingAccount",
    13: "CashAccount",
    14: "CreditCardAccount",
    15: "LoanAccount",
    16: "InvestmentAccount",
    17: "ForexAccount",
    20: "Category",
    29: "Payee",
    37: "Transaction",
    38: "DepositTransaction",
    43: "ReconcileTransaction",
    44: "RefundTransaction",
    46: "TransferDepositTransaction",
    47: "TransferWithdrawTransaction",
    48: "WithdrawTransaction",
}


def cd_seconds(moment: datetime) -> float:
    return moment.timestamp() - CD_EPOCH_OFFSET


@dataclass(frozen=True)
class FxAccount:
    pk: int
    name: str
    currency: str = "EUR"
    ent: int = 11
    opening: float = 0.0
    archived: int = 0


@dataclass(frozen=True)
class FxCategory:
    pk: int
    name: str
    parent: int | None = None
    type: int = 1


@dataclass(frozen=True)
class FxPayee:
    pk: int
    name: str


@dataclass(frozen=True)
class FxTransaction:
    pk: int
    ent: int
    account: int
    amount: float
    date: datetime
    desc: str = ""
    notes: str = ""
    payee: int | None = None
    recipient_account: int | None = None
    sender_account: int | None = None
    recipient_transaction: int | None = None
    categories: tuple[int, ...] = field(default_factory=tuple)
    created: datetime | None = None
    status: int = 2


SCHEMA = """
CREATE TABLE Z_PRIMARYKEY (
  Z_ENT INTEGER PRIMARY KEY, Z_NAME VARCHAR, Z_SUPER INTEGER, Z_MAX INTEGER
);
CREATE TABLE ZSYNCOBJECT (
  Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER,
  ZNAME VARCHAR, ZCURRENCYNAME VARCHAR, ZOPENINGBALANCE FLOAT, ZARCHIVED INTEGER,
  ZNAME2 VARCHAR, ZPARENTCATEGORY INTEGER, ZTYPE2 INTEGER,
  ZNAME5 VARCHAR,
  ZACCOUNT2 INTEGER, ZAMOUNT1 FLOAT, ZDATE1 TIMESTAMP, ZDESC2 VARCHAR, ZNOTES1 VARCHAR,
  ZPAYEE2 INTEGER, ZRECIPIENTACCOUNT1 INTEGER, ZSENDERACCOUNT INTEGER,
  ZRECIPIENTTRANSACTION INTEGER, ZSENDERTRANSACTION INTEGER,
  ZOBJECTCREATIONDATE TIMESTAMP, ZSTATUS1 INTEGER, ZRECONCILED INTEGER
);
CREATE TABLE ZCATEGORYASSIGMENT (Z_PK INTEGER PRIMARY KEY, ZTRANSACTION INTEGER, ZCATEGORY INTEGER);
"""


def build_db(
    path: Path,
    accounts: list[FxAccount],
    categories: list[FxCategory],
    payees: list[FxPayee],
    transactions: list[FxTransaction],
    entity_shift: int = 0,
) -> None:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO Z_PRIMARYKEY VALUES (?, ?, 0, 0)",
        [(ent + entity_shift, name) for ent, name in ENTITIES.items()],
    )
    for a in accounts:
        con.execute(
            "INSERT INTO ZSYNCOBJECT"
            " (Z_PK, Z_ENT, ZNAME, ZCURRENCYNAME, ZOPENINGBALANCE, ZARCHIVED)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (a.pk, a.ent + entity_shift, a.name, a.currency, a.opening, a.archived),
        )
    for c in categories:
        con.execute(
            "INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZNAME2, ZPARENTCATEGORY, ZTYPE2)"
            " VALUES (?, ?, ?, ?, ?)",
            (c.pk, 20 + entity_shift, c.name, c.parent, c.type),
        )
    for p in payees:
        con.execute(
            "INSERT INTO ZSYNCOBJECT (Z_PK, Z_ENT, ZNAME5) VALUES (?, ?, ?)",
            (p.pk, 29 + entity_shift, p.name),
        )
    for t in transactions:
        created = t.created or t.date
        con.execute(
            "INSERT INTO ZSYNCOBJECT"
            " (Z_PK, Z_ENT, ZACCOUNT2, ZAMOUNT1, ZDATE1, ZDESC2, ZNOTES1, ZPAYEE2,"
            " ZRECIPIENTACCOUNT1, ZSENDERACCOUNT, ZRECIPIENTTRANSACTION,"
            " ZOBJECTCREATIONDATE, ZSTATUS1, ZRECONCILED)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                t.pk,
                t.ent + entity_shift,
                t.account,
                t.amount,
                cd_seconds(t.date),
                t.desc,
                t.notes,
                t.payee,
                t.recipient_account,
                t.sender_account,
                t.recipient_transaction,
                cd_seconds(created),
                t.status,
            ),
        )
        for cat in t.categories:
            con.execute(
                "INSERT INTO ZCATEGORYASSIGMENT (ZTRANSACTION, ZCATEGORY) VALUES (?, ?)",
                (t.pk, cat),
            )
    con.commit()
    con.close()
