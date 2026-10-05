import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from smoothment.money import to_decimal
from smoothment.moneywiz.model import (
    Account,
    Category,
    CategoryType,
    MoneyWizSnapshot,
    MoneyWizStoreError,
    Payee,
    Transaction,
    TransactionKind,
)

CD_EPOCH_OFFSET = 978307200
ACCOUNT_ENTITIES = (
    "Account",
    "BankChequeAccount",
    "BankSavingAccount",
    "CashAccount",
    "CreditCardAccount",
    "LoanAccount",
    "InvestmentAccount",
    "ForexAccount",
)
KIND_BY_ENTITY: dict[str, TransactionKind] = {
    "DepositTransaction": "deposit",
    "WithdrawTransaction": "withdraw",
    "RefundTransaction": "refund",
    "TransferDepositTransaction": "transfer_in",
    "TransferWithdrawTransaction": "transfer_out",
    "ReconcileTransaction": "reconcile",
}
CATEGORY_TYPES: dict[int, CategoryType] = {1: "expense", 2: "income"}
PATH_SEPARATOR = " > "


def _cd_datetime(value: float) -> datetime:
    return datetime.fromtimestamp(value + CD_EPOCH_OFFSET)


def _copy_store(db_path: Path) -> tuple[Path, Path]:
    if not db_path.is_file():
        raise MoneyWizStoreError(f"MoneyWiz store not found: {db_path}")
    temp_dir = Path(tempfile.mkdtemp(prefix="smoothment-moneywiz-"))
    try:
        copy = temp_dir / db_path.name
        shutil.copy2(db_path, copy)
        for suffix in ("-wal", "-shm"):
            sidecar = db_path.with_name(db_path.name + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, copy.with_name(copy.name + suffix))
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return temp_dir, copy


def _entity_ids(con: sqlite3.Connection) -> dict[str, int]:
    try:
        rows = con.execute("SELECT Z_NAME, Z_ENT FROM Z_PRIMARYKEY").fetchall()
    except sqlite3.DatabaseError as exc:
        raise MoneyWizStoreError(f"Not a MoneyWiz store (no Z_PRIMARYKEY): {exc}") from exc
    ids = {name: int(ent) for name, ent in rows}
    if "Category" not in ids or "Payee" not in ids:
        raise MoneyWizStoreError("Not a MoneyWiz store: Category/Payee entities missing")
    return ids


def _read_accounts(con: sqlite3.Connection, ids: dict[str, int]) -> dict[int, Account]:
    by_ent = {ids[name]: name for name in ACCOUNT_ENTITIES if name in ids}
    placeholders = ",".join("?" * len(by_ent))
    rows = con.execute(
        f"SELECT Z_PK, Z_ENT, ZNAME, ZCURRENCYNAME, ZOPENINGBALANCE, ZARCHIVED FROM ZSYNCOBJECT"
        f" WHERE Z_ENT IN ({placeholders})",
        tuple(by_ent),
    )
    accounts: dict[int, Account] = {}
    for pk, ent, name, currency, opening, archived in rows:
        if not name:
            continue
        entity = by_ent[int(ent)]
        kind = "Account" if entity == "Account" else entity.removesuffix("Account")
        accounts[int(pk)] = Account(
            pk=int(pk),
            name=name,
            currency=currency or "",
            kind=kind,
            opening_balance=to_decimal(opening or 0.0),
            archived=bool(archived),
        )
    return accounts


def _read_categories(con: sqlite3.Connection, ids: dict[str, int]) -> dict[int, Category]:
    raw: dict[int, tuple[str, int | None, int]] = {}
    for pk, name, parent, ctype in con.execute(
        "SELECT Z_PK, ZNAME2, ZPARENTCATEGORY, ZTYPE2 FROM ZSYNCOBJECT WHERE Z_ENT = ?",
        (ids["Category"],),
    ):
        if not name or name == "???":
            continue
        raw[int(pk)] = (name, int(parent) if parent is not None else None, int(ctype or 0))

    def path_of(pk: int) -> str | None:
        parts: list[str] = []
        seen: set[int] = set()
        current: int | None = pk
        while current is not None and current in raw:
            if current in seen:
                return None
            seen.add(current)
            name, parent, _ = raw[current]
            parts.insert(0, name)
            current = parent
        return PATH_SEPARATOR.join(parts)

    categories: dict[int, Category] = {}
    for pk, (name, _parent, ctype) in raw.items():
        if ctype not in CATEGORY_TYPES:
            continue
        path = path_of(pk)
        if path is None:
            continue
        categories[pk] = Category(pk=pk, name=name, path=path, type=CATEGORY_TYPES[ctype])
    return categories


def _read_payees(con: sqlite3.Connection, ids: dict[str, int]) -> dict[int, Payee]:
    return {
        int(pk): Payee(pk=int(pk), name=name)
        for pk, name in con.execute(
            "SELECT Z_PK, ZNAME5 FROM ZSYNCOBJECT WHERE Z_ENT = ?", (ids["Payee"],)
        )
        if name
    }


def _read_assignments(
    con: sqlite3.Connection, categories: dict[int, Category]
) -> dict[int, tuple[str, ...]]:
    result: dict[int, list[str]] = {}
    for tx, cat in con.execute("SELECT ZTRANSACTION, ZCATEGORY FROM ZCATEGORYASSIGMENT"):
        if tx is not None and cat is not None and int(cat) in categories:
            result.setdefault(int(tx), []).append(categories[int(cat)].path)
    return {tx: tuple(paths) for tx, paths in result.items()}


def _read_transactions(
    con: sqlite3.Connection,
    ids: dict[str, int],
    accounts: dict[int, Account],
    payees: dict[int, Payee],
    assignments: dict[int, tuple[str, ...]],
) -> tuple[Transaction, ...]:
    kind_by_id = {ids[name]: kind for name, kind in KIND_BY_ENTITY.items() if name in ids}
    placeholders = ",".join("?" * len(kind_by_id))
    rows = con.execute(
        "SELECT Z_PK, Z_ENT, ZACCOUNT2, ZAMOUNT1, ZDATE1, ZDESC2, ZNOTES1, ZPAYEE2,"
        " ZRECIPIENTACCOUNT1, ZSENDERACCOUNT, ZRECIPIENTTRANSACTION, ZOBJECTCREATIONDATE,"
        f" ZSTATUS1 FROM ZSYNCOBJECT WHERE Z_ENT IN ({placeholders})",
        tuple(kind_by_id),
    ).fetchall()
    out_by_recipient = {
        int(row[10]): int(row[0])
        for row in rows
        if kind_by_id[int(row[1])] == "transfer_out" and row[10] is not None
    }
    out: list[Transaction] = []
    for (
        pk,
        ent,
        acc,
        amount,
        when,
        desc,
        notes,
        payee,
        recipient,
        sender,
        recipient_tx,
        created,
        status,
    ) in rows:
        account = accounts.get(int(acc)) if acc is not None else None
        if account is None or amount is None or when is None:
            continue
        kind = kind_by_id[int(ent)]
        other_pk = (
            recipient if kind == "transfer_out" else sender if kind == "transfer_in" else None
        )
        other_account = accounts.get(int(other_pk)) if other_pk is not None else None
        other = other_account.name if other_account is not None else None
        linked = (
            int(recipient_tx)
            if kind == "transfer_out" and recipient_tx is not None
            else out_by_recipient.get(int(pk))
            if kind == "transfer_in"
            else None
        )
        out.append(
            Transaction(
                pk=int(pk),
                kind=kind,
                account=account.name,
                account_pk=account.pk,
                amount=to_decimal(float(amount)),
                date=_cd_datetime(float(when)),
                description=desc or "",
                notes=notes or "",
                payee=payees[int(payee)].name
                if payee is not None and int(payee) in payees
                else None,
                other_account=other,
                categories=assignments.get(int(pk), ()),
                created=_cd_datetime(float(created if created is not None else when)),
                status=int(status or 0),
                other_account_pk=other_account.pk if other_account is not None else None,
                linked_pk=linked,
            )
        )
    out.sort(key=lambda t: (t.date, t.pk))
    return tuple(out)


def read_snapshot(db_path: Path) -> MoneyWizSnapshot:
    temp_dir, copy = _copy_store(db_path)
    try:
        con = sqlite3.connect(f"{copy.as_uri()}?mode=ro", uri=True)
        try:
            ids = _entity_ids(con)
            accounts = _read_accounts(con, ids)
            categories = _read_categories(con, ids)
            payees = _read_payees(con, ids)
            assignments = _read_assignments(con, categories)
            transactions = _read_transactions(con, ids, accounts, payees, assignments)
        except sqlite3.OperationalError as exc:
            raise MoneyWizStoreError(f"Unexpected MoneyWiz store schema: {exc}") from exc
        finally:
            con.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return MoneyWizSnapshot(
        accounts=tuple(accounts.values()),
        categories=tuple(sorted(categories.values(), key=lambda c: c.path)),
        payees=tuple(payees.values()),
        transactions=transactions,
    )
