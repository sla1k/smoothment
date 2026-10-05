import sqlite3
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.moneywiz import model
from smoothment.moneywiz.model import MoneyWizSnapshot, Transaction, normalize_text
from smoothment.moneywiz.reader import MoneyWizStoreError, read_snapshot
from tests.conftest import MakeDb
from tests.moneywiz_fixture import FxAccount, FxCategory, FxPayee, FxTransaction, build_db


def test_fixture_builder_creates_expected_rows(moneywiz_db: MakeDb) -> None:
    path: Path = moneywiz_db(
        [FxAccount(1, "Revolut")],
        [FxCategory(10, "Food"), FxCategory(11, "Groceries", parent=10)],
        [FxPayee(20, "Apple")],
        [
            FxTransaction(
                30, 48, 1, -4.38, datetime(2026, 6, 26, 15, 42), payee=20, categories=(11,)
            )
        ],
    )
    con = sqlite3.connect(path)
    try:
        assert con.execute("SELECT COUNT(*) FROM ZSYNCOBJECT").fetchone()[0] == 5
        assert con.execute("SELECT COUNT(*) FROM ZCATEGORYASSIGMENT").fetchone()[0] == 1
    finally:
        con.close()


def _sample(moneywiz_db: MakeDb) -> Path:
    return moneywiz_db(
        [
            FxAccount(1, "Revolut", "EUR", opening=-22.91999999998177),
            FxAccount(2, "Shared", "EUR"),
            FxAccount(3, "Black", "RUB", ent=14, archived=1),
        ],
        [
            FxCategory(10, "Food & Dining"),
            FxCategory(11, "Groceries", parent=10),
            FxCategory(12, "Salary", type=2),
            FxCategory(13, "???"),
            FxCategory(14, "Broken", type=65535),
        ],
        [FxPayee(20, "Sample\xa0Sports\xa0Club"), FxPayee(21, "Sample Employer")],
        [
            FxTransaction(
                30,
                48,
                1,
                -4.38,
                datetime(2026, 6, 26, 15, 42),
                desc="Sample Sports Club",
                notes="smt:abc123",
                payee=20,
                categories=(11,),
            ),
            FxTransaction(
                31, 38, 1, 2500.0, datetime(2026, 7, 1), desc="Salary", payee=21, categories=(12,)
            ),
            FxTransaction(
                32,
                47,
                1,
                -300.0,
                datetime(2026, 6, 25),
                desc="To Shared",
                recipient_account=2,
                recipient_transaction=33,
            ),
            FxTransaction(
                33, 46, 2, 300.0, datetime(2026, 6, 25), desc="From Revolut", sender_account=1
            ),
            FxTransaction(34, 44, 1, 670.0, datetime(2026, 6, 26), desc="Viator refund"),
        ],
    )


def test_reads_accounts_with_decimal_opening_balance(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(_sample(moneywiz_db))
    revolut = snap.account("revolut")
    assert revolut is not None
    assert revolut.opening_balance == Decimal("-22.92")
    assert revolut.kind == "BankCheque"
    black = snap.account("Black")
    assert black is not None and black.archived is True and black.kind == "CreditCard"


def test_category_paths_and_skips_garbage(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(_sample(moneywiz_db))
    paths = {c.path: c.type for c in snap.categories}
    assert paths == {
        "Food & Dining": "expense",
        "Food & Dining > Groceries": "expense",
        "Salary": "income",
    }


def test_payee_names_keep_nbsp(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(_sample(moneywiz_db))
    names = {p.name for p in snap.payees}
    assert "Sample\xa0Sports\xa0Club" in names


def test_transactions_kinds_amounts_and_links(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(_sample(moneywiz_db))
    by_pk = {t.pk: t for t in snap.transactions}
    assert by_pk[30].kind == "withdraw"
    assert by_pk[30].amount == Decimal("-4.38")
    assert by_pk[30].payee == "Sample\xa0Sports\xa0Club"
    assert by_pk[30].categories == ("Food & Dining > Groceries",)
    assert by_pk[30].date == datetime(2026, 6, 26, 15, 42)
    assert by_pk[31].kind == "deposit" and by_pk[31].categories == ("Salary",)
    assert by_pk[32].kind == "transfer_out" and by_pk[32].other_account == "Shared"
    assert by_pk[33].kind == "transfer_in" and by_pk[33].other_account == "Revolut"
    assert by_pk[34].kind == "refund" and by_pk[34].payee is None


def test_transactions_in_window_and_memo_lookup(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(_sample(moneywiz_db))
    june = snap.transactions_in("Revolut", date(2026, 6, 25), date(2026, 6, 26))
    assert sorted(t.pk for t in june) == [30, 32, 34]
    assert [t.pk for t in snap.find_by_memo("smt:abc123")] == [30]


def test_reader_leaves_source_untouched_and_cleans_temp(
    moneywiz_db: MakeDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _sample(moneywiz_db)
    before = path.read_bytes()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        "smoothment.moneywiz.reader.tempfile.mkdtemp",
        lambda prefix: real_mkdtemp(prefix=prefix, dir=scratch),
    )
    read_snapshot(path)
    assert path.read_bytes() == before
    assert list(scratch.iterdir()) == []


def test_reader_connects_read_only_to_the_temp_copy(
    moneywiz_db: MakeDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _sample(moneywiz_db)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        "smoothment.moneywiz.reader.tempfile.mkdtemp",
        lambda prefix: real_mkdtemp(prefix=prefix, dir=scratch),
    )
    real_connect = sqlite3.connect
    targets: list[str] = []

    def spy(database: str, *, uri: bool) -> sqlite3.Connection:
        targets.append(database)
        return real_connect(database, uri=uri)

    monkeypatch.setattr("smoothment.moneywiz.reader.sqlite3.connect", spy)
    read_snapshot(path)
    assert len(targets) == 1
    assert targets[0].startswith("file:") and targets[0].endswith("?mode=ro")
    assert str(scratch) in targets[0]
    assert str(path.parent) not in targets[0].replace(str(scratch), "")


def test_copy_failure_cleans_temp_dir_and_propagates(
    moneywiz_db: MakeDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _sample(moneywiz_db)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        "smoothment.moneywiz.reader.tempfile.mkdtemp",
        lambda prefix: real_mkdtemp(prefix=prefix, dir=scratch),
    )

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("smoothment.moneywiz.reader.shutil.copy2", _boom)
    with pytest.raises(OSError):
        read_snapshot(path)
    assert list(scratch.iterdir()) == []


def test_non_moneywiz_sqlite_raises(tmp_path: Path) -> None:
    other = tmp_path / "other.sqlite"
    con = sqlite3.connect(other)
    try:
        con.executescript("CREATE TABLE t (x);")
    finally:
        con.close()
    with pytest.raises(MoneyWizStoreError):
        read_snapshot(other)


def test_missing_column_raises_store_error(moneywiz_db: MakeDb) -> None:
    path = _sample(moneywiz_db)
    con = sqlite3.connect(path)
    try:
        con.execute("ALTER TABLE ZSYNCOBJECT DROP COLUMN ZNOTES1")
        con.commit()
    finally:
        con.close()
    with pytest.raises(MoneyWizStoreError, match="ZNOTES1"):
        read_snapshot(path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(MoneyWizStoreError):
        read_snapshot(tmp_path / "missing.sqlite")


def test_normalize_text() -> None:
    assert normalize_text("Sample\xa0Sports  Club ") == "Sample Sports Club"
    assert normalize_text(None) == ""


def _tx(snap: MoneyWizSnapshot, pk: int) -> Transaction:
    found = snap.by_pk(pk)
    assert found is not None
    return found


def test_store_error_lives_in_model_and_is_reexported_by_reader() -> None:
    assert MoneyWizStoreError is model.MoneyWizStoreError


def test_reconcile_rows_are_read_and_counted_in_the_balance(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(
        moneywiz_db(
            [FxAccount(1, "Revolut", opening=100.0)],
            [],
            [],
            [
                FxTransaction(30, 48, 1, -10.0, datetime(2026, 6, 1, 9)),
                FxTransaction(31, 43, 1, 2.5, datetime(2026, 6, 2, 9)),
                FxTransaction(32, 38, 1, 40.0, datetime(2026, 6, 3, 9)),
            ],
        )
    )
    assert {t.pk: t.kind for t in snap.transactions}[31] == "reconcile"
    assert snap.balance("Revolut", date(2026, 6, 2)) == Decimal("92.50")
    assert snap.balance("Revolut", date(2026, 6, 3)) == Decimal("132.50")


def test_balance_before_first_transaction_is_the_opening_balance(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(
        moneywiz_db(
            [FxAccount(1, "Revolut", opening=-22.91999999998177)],
            [],
            [],
            [FxTransaction(30, 48, 1, -10.0, datetime(2026, 6, 10, 9))],
        )
    )
    assert snap.balance("Revolut", date(2026, 6, 9)) == Decimal("-22.92")
    assert snap.balance("Revolut", date(2026, 6, 10)) == Decimal("-32.92")


def test_balance_of_unknown_account_is_none(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(_sample(moneywiz_db))
    assert snap.balance("Nowhere", date(2026, 7, 1)) is None


def test_balance_compares_names_normalized_and_casefolded(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(moneywiz_db([FxAccount(1, "Club\xa0Card", opening=5.0)], [], [], []))
    assert snap.balance("  club card ", date(2026, 1, 1)) == Decimal("5")


def test_transfer_legs_point_at_each_other(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(_sample(moneywiz_db))
    assert _tx(snap, 32).linked_pk == 33
    assert _tx(snap, 33).linked_pk == 32
    assert _tx(snap, 33).other_account_pk == 1
    assert _tx(snap, 32).other_account_pk == 2
    assert _tx(snap, 30).linked_pk is None
    assert _tx(snap, 30).account_pk == 1


def test_transfer_in_without_partner_has_no_link(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(
        moneywiz_db(
            [FxAccount(1, "Revolut"), FxAccount(2, "Shared")],
            [],
            [],
            [FxTransaction(33, 46, 2, 300.0, datetime(2026, 6, 25), sender_account=1)],
        )
    )
    assert _tx(snap, 33).linked_pk is None


def test_by_pk_unknown_is_none(moneywiz_db: MakeDb) -> None:
    assert read_snapshot(_sample(moneywiz_db)).by_pk(999) is None


@pytest.mark.parametrize(
    ("notes", "expected"),
    [
        ("", ()),
        ("smt:0123456789ab", ("smt:0123456789ab",)),
        ("paid; smt:0123456789ab; ok", ("smt:0123456789ab",)),
        ("smt:aaaaaaaaaaaa then smt:bbbbbbbbbbbb end", ("smt:aaaaaaaaaaaa", "smt:bbbbbbbbbbbb")),
        ("smt:abc123 too short", ()),
    ],
)
def test_tags_extracts_every_tag_in_order(notes: str, expected: tuple[str, ...]) -> None:
    t = Transaction(
        pk=1,
        kind="withdraw",
        account="Revolut",
        account_pk=1,
        amount=Decimal("-1"),
        date=datetime(2026, 6, 1),
        description="",
        notes=notes,
        payee=None,
        other_account=None,
        categories=(),
        created=datetime(2026, 6, 1),
        status=2,
    )
    assert t.tags == expected


def test_archived_and_live_accounts_with_one_name_resolve_to_the_live_one(
    moneywiz_db: MakeDb,
) -> None:
    snap = read_snapshot(
        moneywiz_db(
            [FxAccount(1, "Revolut", archived=1), FxAccount(2, "REVOLUT")],
            [],
            [],
            [
                FxTransaction(30, 48, 1, -1.0, datetime(2026, 6, 1, 9)),
                FxTransaction(31, 48, 2, -2.0, datetime(2026, 6, 1, 9)),
            ],
        )
    )
    account = snap.account("revolut")
    assert account is not None and account.pk == 2
    found = snap.transactions_in("Revolut", date(2026, 6, 1), date(2026, 6, 1))
    assert [t.pk for t in found] == [31]


def test_single_archived_account_is_used_when_no_live_one_matches(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(
        moneywiz_db(
            [FxAccount(1, "Black", archived=1), FxAccount(2, "Revolut")],
            [],
            [],
            [FxTransaction(30, 48, 1, -1.0, datetime(2026, 6, 1, 9))],
        )
    )
    account = snap.account("Black")
    assert account is not None and account.pk == 1
    assert len(snap.transactions_in("Black", date(2026, 6, 1), date(2026, 6, 1))) == 1


def test_two_live_accounts_with_one_name_raise(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(
        moneywiz_db([FxAccount(1, "Revolut"), FxAccount(2, "revolut")], [], [], [])
    )
    for call in (
        lambda: snap.account("Revolut"),
        lambda: snap.transactions_in("Revolut", date(2026, 6, 1), date(2026, 6, 2)),
        lambda: snap.balance("Revolut", date(2026, 6, 1)),
    ):
        with pytest.raises(MoneyWizStoreError, match="Revolut"):
            call()


def test_two_archived_accounts_with_one_name_raise(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(
        moneywiz_db([FxAccount(1, "Old", archived=1), FxAccount(2, "Old", archived=1)], [], [], [])
    )
    with pytest.raises(MoneyWizStoreError, match="Old"):
        snap.account("Old")


def test_unknown_account_gives_none_and_no_transactions(moneywiz_db: MakeDb) -> None:
    snap = read_snapshot(_sample(moneywiz_db))
    assert snap.account("Nowhere") is None
    assert snap.transactions_in("Nowhere", date(2026, 1, 1), date(2026, 12, 31)) == ()


def test_entity_numbers_come_from_the_store_not_from_constants(tmp_path: Path) -> None:
    path = tmp_path / "shifted.sqlite"
    build_db(
        path,
        [FxAccount(1, "Revolut", opening=10.0), FxAccount(2, "Shared")],
        [FxCategory(10, "Food")],
        [FxPayee(20, "Apple")],
        [
            FxTransaction(30, 48, 1, -4.0, datetime(2026, 6, 1, 9), payee=20, categories=(10,)),
            FxTransaction(31, 43, 1, 1.0, datetime(2026, 6, 2, 9)),
            FxTransaction(
                32,
                47,
                1,
                -3.0,
                datetime(2026, 6, 3, 9),
                recipient_account=2,
                recipient_transaction=33,
            ),
            FxTransaction(33, 46, 2, 3.0, datetime(2026, 6, 3, 9), sender_account=1),
        ],
        entity_shift=100,
    )
    snap = read_snapshot(path)
    assert [c.path for c in snap.categories] == ["Food"]
    assert [p.name for p in snap.payees] == ["Apple"]
    assert {t.pk: t.kind for t in snap.transactions} == {
        30: "withdraw",
        31: "reconcile",
        32: "transfer_out",
        33: "transfer_in",
    }
    assert _tx(snap, 33).linked_pk == 32
    assert snap.balance("Revolut", date(2026, 6, 3)) == Decimal("4")
