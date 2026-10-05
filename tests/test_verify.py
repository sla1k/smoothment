from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from smoothment.classify.model import ClassifiedRow
from smoothment.config import Config
from smoothment.convert import ConvertResult, run_convert
from smoothment.link import Transfer
from smoothment.moneywiz.model import MoneyWizSnapshot, Transaction, TransactionKind
from smoothment.moneywiz.reader import MoneyWizStoreError
from smoothment.reconcile import Match, TransferUnit
from smoothment.report import render_verify_report
from smoothment.verify import NO_BALANCE, BalanceEntry, VerifyResult, run_verify, wrong_transfers
from tests.classify_fixtures import make_row
from tests.conftest import (
    ROUNDUPS_CONFIG,
    ROUNDUPS_CSV,
    STATEMENT_CONFIG,
    inflate_wise_input_rows,
)
from tests.snapshot_fixtures import imported_snapshot, snapshot_of

OPENINGS = {
    "BBVA": Decimal("214.09"),
    "Revolut": Decimal("1000.00"),
    "Shared": Decimal("109.99"),
    "Travel": Decimal("10.00"),
}
ROUNDUP_OPENINGS = {"Shared": Decimal("100.00")}


@pytest.fixture
def config(make_config: Callable[[str], Config]) -> Config:
    return make_config(STATEMENT_CONFIG)


@pytest.fixture
def imported(statement_folder: Path, config: Config) -> tuple[ConvertResult, MoneyWizSnapshot]:
    result = run_convert(statement_folder, config, dry_run=True)
    return result, imported_snapshot(result, OPENINGS)


def without(snapshot: MoneyWizSnapshot, *pks: int) -> MoneyWizSnapshot:
    kept = tuple(t for t in snapshot.transactions if t.pk not in pks)
    return replace(snapshot, transactions=kept)


def changed(snapshot: MoneyWizSnapshot, pk: int, **fields: Any) -> MoneyWizSnapshot:
    swapped = tuple(replace(t, **fields) if t.pk == pk else t for t in snapshot.transactions)
    return replace(snapshot, transactions=swapped)


def find(snapshot: MoneyWizSnapshot, account: str, amount: str) -> Transaction:
    (found,) = [
        t for t in snapshot.transactions if t.account == account and t.amount == Decimal(amount)
    ]
    return found


def entry(result: VerifyResult, account: str) -> BalanceEntry:
    (found,) = [e for e in result.balances if e.account == account]
    return found


# --- clean import --------------------------------------------------------------------


def test_clean_import_gives_an_empty_report(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported

    result = run_verify(statement_folder, config, snapshot)

    assert (result.missing, result.wrong, result.extra) == ((), (), ())
    assert result.clean is True
    compared = {e.account: e for e in result.balances if e.note is None}
    assert set(compared) == {"BBVA", "Revolut", "Shared", "Travel", "Santander", "Wise"}
    assert all(e.difference == 0 for e in compared.values())
    assert compared["Wise"].statement == Decimal("0.17")
    assert compared["Shared"].day == datetime(2026, 8, 9).date()


def test_accounts_without_a_running_balance_are_flagged(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    result = run_verify(statement_folder, config, imported[1])

    flagged = {e.account for e in result.balances if e.note == NO_BALANCE}
    assert flagged == {"Safety", "Black", "Platinum"}
    for e in result.balances:
        if e.note == NO_BALANCE:
            assert (e.day, e.statement, e.moneywiz, e.difference) == (None, None, None, None)


def test_verify_never_writes_the_csv(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    before = (statement_folder / "moneywiz_import.csv").read_text()

    run_verify(statement_folder, config, imported[1])

    assert (statement_folder / "moneywiz_import.csv").read_text() == before


# --- missing ---------------------------------------------------------------------------


def test_a_row_deleted_in_moneywiz_is_missing_and_explains_the_balance(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    cashback = find(snapshot, "Wise", "0.87")

    result = run_verify(statement_folder, config, without(snapshot, cashback.pk))

    (item,) = result.missing
    assert (item.account, item.amount) == ("Wise", Decimal("0.87"))
    assert "Cashback" in item.description
    assert item.day == datetime(2026, 9, 1).date()
    assert (result.wrong, result.extra) == ((), ())
    assert result.clean is False
    wise = entry(result, "Wise")
    assert wise.difference == Decimal("-0.87")
    assert wise.missing == Decimal("0.87")
    assert wise.unexplained == 0


def test_a_missing_transfer_is_booked_in_both_accounts(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    out = find(snapshot, "Revolut", "-44.00")
    assert out.linked_pk is not None

    result = run_verify(statement_folder, config, without(snapshot, out.pk, out.linked_pk))

    (item,) = result.missing
    assert item.account == "Revolut -> Wise"
    assert [(p.account, p.amount) for p in item.postings] == [
        ("Revolut", Decimal("-44.00")),
        ("Wise", Decimal("44.00")),
    ]
    assert entry(result, "Wise").missing == Decimal("44.00")
    assert entry(result, "Wise").unexplained == 0
    assert entry(result, "Revolut").unexplained == 0


# --- wrong -----------------------------------------------------------------------------


def test_a_transfer_imported_as_a_plain_row_is_wrong(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    out = find(snapshot, "Revolut", "-44.00")
    plain = changed(
        snapshot, out.pk, kind="withdraw", linked_pk=None, other_account=None, other_account_pk=None
    )
    assert out.linked_pk is not None
    plain = changed(plain, out.linked_pk, kind="deposit", linked_pk=None)

    result = run_verify(statement_folder, config, plain)

    (item,) = result.wrong
    assert item.account == "Revolut"
    assert item.amount == Decimal("-44.00")
    assert item.problem == ("imported as a plain row; expected a transfer between Revolut and Wise")
    assert (result.missing, result.extra) == ((), ())
    assert result.clean is False


def test_a_transfer_to_the_wrong_account_names_both(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    out = find(snapshot, "Revolut", "-200.00")
    wise = next(a for a in snapshot.accounts if a.name == "Wise")
    swapped = changed(snapshot, out.pk, other_account="Wise", other_account_pk=wise.pk)

    result = run_verify(statement_folder, config, swapped)

    (item,) = result.wrong
    assert "Wise" in item.problem
    assert "Safety" in item.problem
    assert item.amount == Decimal("-200.00")


def test_a_plain_statement_row_matched_to_a_moneywiz_transfer_is_not_wrong(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    coffee = find(snapshot, "Shared", "-3.50")
    other = next(a for a in snapshot.accounts if a.name == "Wise")
    as_transfer = changed(
        snapshot, coffee.pk, kind="transfer_out", other_account="Wise", other_account_pk=other.pk
    )

    result = run_verify(statement_folder, config, as_transfer)

    assert result.wrong == ()


def _cross_currency_match(
    kind_of_matched: str, amount_in_moneywiz: str
) -> tuple[Match, MoneyWizSnapshot]:
    outgoing = ClassifiedRow(
        row=make_row(account="Black", amount=Decimal("-50.00"), currency="EUR"),
        kind="own_transfer",
        evidence="test",
    )
    incoming = ClassifiedRow(
        row=make_row(account="Rub", amount=Decimal("5000.00"), currency="RUB"),
        kind="own_transfer",
        evidence="test",
    )
    transfer = Transfer(
        outgoing=outgoing, incoming=incoming, source="Black", destination="Rub", note="paired"
    )
    snapshot = snapshot_of(["Black", "Rub"])
    black, rub = snapshot.accounts
    moment = datetime(2026, 9, 1, 1, 0)

    def make(
        pk: int,
        kind: TransactionKind,
        account: str,
        account_pk: int,
        amount: str,
        other: int,
        linked: int,
    ) -> Transaction:
        return Transaction(
            pk=pk,
            kind=kind,
            account=account,
            account_pk=account_pk,
            amount=Decimal(amount),
            date=moment,
            description="",
            notes="",
            payee=None,
            other_account=None,
            categories=(),
            created=moment,
            status=2,
            other_account_pk=other,
            linked_pk=linked,
        )

    sent = make(1, "transfer_out", "Black", black.pk, "-50.00", rub.pk, 2)
    received = make(2, "transfer_in", "Rub", rub.pk, amount_in_moneywiz, black.pk, 1)
    snapshot = replace(snapshot, transactions=(sent, received))
    matched = sent if kind_of_matched == "out" else received
    leg = outgoing if kind_of_matched == "out" else incoming
    return Match(TransferUnit(transfer), matched, "tag", leg), snapshot


@pytest.mark.parametrize("side", ["out", "in"])
def test_a_cross_currency_transfer_names_the_received_amount_to_set(side: str) -> None:
    match, snapshot = _cross_currency_match(side, "50.00")

    (item,) = wrong_transfers([match], snapshot)

    assert "set the received amount to 5000.00 RUB" in item.problem
    assert (item.account, item.amount) == ("Rub", Decimal("50.00"))


def test_a_cross_currency_transfer_with_the_right_received_amount_is_fine() -> None:
    match, snapshot = _cross_currency_match("out", "5000.00")

    assert wrong_transfers([match], snapshot) == ()


# --- extra -----------------------------------------------------------------------------


def test_a_hand_entered_duplicate_is_extra_and_explains_the_balance(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    cashback = find(snapshot, "Wise", "0.87")
    duplicate = replace(cashback, pk=9000, notes="", payee="Cafe")

    result = run_verify(
        statement_folder,
        config,
        replace(snapshot, transactions=(*snapshot.transactions, duplicate)),
    )

    (item,) = result.extra
    assert (item.account, item.amount, item.transaction.pk) == ("Wise", Decimal("0.87"), 9000)
    assert item.description.startswith("Cafe")
    assert (result.missing, result.wrong) == ((), ())
    wise = entry(result, "Wise")
    assert wise.difference == Decimal("0.87")
    assert wise.extra == Decimal("0.87")
    assert wise.unexplained == 0
    assert result.clean is False


def test_extra_ignores_rows_outside_the_statement_range_and_reconcile_rows(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    coffee = find(snapshot, "Shared", "-3.50")
    before = replace(coffee, pk=9000, notes="", date=datetime(2026, 7, 31, 12, 0))
    after = replace(coffee, pk=9001, notes="", date=datetime(2026, 8, 10, 12, 0))
    reconcile_row = replace(coffee, pk=9002, notes="", kind="reconcile")
    inside_range_edge = replace(coffee, pk=9003, notes="", date=datetime(2026, 8, 9, 23, 0))

    result = run_verify(
        statement_folder,
        config,
        replace(
            snapshot,
            transactions=(*snapshot.transactions, before, after, reconcile_row, inside_range_edge),
        ),
    )

    assert [item.transaction.pk for item in result.extra] == [9003]


def test_extra_covers_a_mapped_pocket_account(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    travel = find(snapshot, "Travel", "0.01")
    stray = replace(travel, pk=9000, notes="", amount=Decimal("7.00"), kind="deposit")

    result = run_verify(
        statement_folder, config, replace(snapshot, transactions=(*snapshot.transactions, stray))
    )

    assert [(i.account, i.amount) for i in result.extra] == [("Travel", Decimal("7.00"))]


def test_extra_is_reported_once_when_two_statements_cover_one_account(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)
    (roundups_folder / "revolut_shared_2.csv").write_text(
        (roundups_folder / "revolut_shared.csv").read_text()
    )
    first = run_convert(roundups_folder, config, dry_run=True)
    snapshot = imported_snapshot(first, ROUNDUP_OPENINGS)
    template = snapshot.transactions[-1]
    stray = replace(template, pk=9000, notes="", amount=Decimal("-8.00"), kind="withdraw")

    result = run_verify(
        roundups_folder, config, replace(snapshot, transactions=(*snapshot.transactions, stray))
    )

    assert len(first.files) == 2
    assert [i.transaction.pk for i in result.extra] == [9000]


# --- balances ----------------------------------------------------------------------------


def test_a_pending_row_explains_a_balance_difference(
    statement_folder: Path, config: Config
) -> None:
    result = run_convert(statement_folder, config, dry_run=True)
    snapshot = imported_snapshot(result, {**OPENINGS, "Shared": Decimal("100.00")})

    verified = run_verify(statement_folder, config, snapshot)

    shared = entry(verified, "Shared")
    assert shared.difference == Decimal("-9.99")
    assert shared.pending == Decimal("-9.99")
    assert shared.unexplained == 0
    assert (verified.missing, verified.wrong, verified.extra) == ((), (), ())
    assert verified.clean is True


def test_an_unknown_account_has_no_moneywiz_balance(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    reduced = replace(
        snapshot,
        accounts=tuple(a for a in snapshot.accounts if a.name != "Wise"),
        transactions=tuple(
            t for t in snapshot.transactions if "Wise" not in (t.account, t.other_account)
        ),
    )

    result = run_verify(statement_folder, config, reduced)

    wise = entry(result, "Wise")
    assert (wise.moneywiz, wise.difference) == (None, None)
    assert result.missing


def test_a_hidden_pocket_chain_is_left_out(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG.replace('Travel = "Travel"', 'Travel = "hidden"'))
    converted = run_convert(statement_folder, config, dry_run=True)
    snapshot = imported_snapshot(converted, OPENINGS)

    result = run_verify(statement_folder, config, snapshot)

    assert "Travel" not in {e.account for e in result.balances}
    assert "Deposit" not in {e.chain for e in result.balances}
    assert entry(result, "Shared").chain == "Current"


def test_two_live_accounts_with_one_name_are_a_store_error(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    wise = next(a for a in snapshot.accounts if a.name == "Wise")
    doubled = replace(snapshot, accounts=(*snapshot.accounts, replace(wise, pk=99)))

    with pytest.raises(MoneyWizStoreError):
        run_verify(statement_folder, config, doubled)


# --- lumps -------------------------------------------------------------------------------


def test_a_lump_in_moneywiz_counts_for_all_its_rows(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)
    converted = run_convert(roundups_folder, config, dry_run=True)
    snapshot = imported_snapshot(converted, ROUNDUP_OPENINGS)

    result = run_verify(roundups_folder, config, snapshot)

    assert len(converted.lumps) == 1
    assert (result.missing, result.wrong, result.extra) == ((), (), ())
    assert result.clean is True
    assert {e.account for e in result.balances} == {"Shared", "Travel"}


def test_a_lump_missing_from_moneywiz_is_reported_once(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)
    converted = run_convert(roundups_folder, config, dry_run=True)
    snapshot = imported_snapshot(converted, ROUNDUP_OPENINGS)
    lump = next(t for t in snapshot.transactions if "smt-lump:" in t.notes)
    assert lump.linked_pk is not None

    result = run_verify(roundups_folder, config, without(snapshot, lump.pk, lump.linked_pk))

    (item,) = result.missing
    assert item.amount == Decimal("-0.60")
    assert item.account == "Shared -> Travel"
    assert "roundups lump of 3 rows" in item.description
    assert entry(result, "Travel").missing == Decimal("0.60")
    assert entry(result, "Travel").unexplained == 0


# --- overlapping statements and lumps ------------------------------------------------------

ROUNDUP_LINES = ROUNDUPS_CSV.splitlines()
MONTH_ONE = "\n".join(ROUNDUP_LINES[:6])
MONTH_TWO = "\n".join([ROUNDUP_LINES[0], *ROUNDUP_LINES[4:]])


def statement_month(tmp_path: Path, name: str, text: str) -> Path:
    folder = tmp_path / name / "2026_08"
    folder.mkdir(parents=True)
    (folder / "revolut_shared.csv").write_text(text)
    return folder


def stacked(first: MoneyWizSnapshot, second: MoneyWizSnapshot) -> MoneyWizSnapshot:
    """`first` with the transactions of `second` added under fresh pks."""
    assert [a.name for a in first.accounts] == [a.name for a in second.accounts]
    offset = 1 + max(t.pk for t in first.transactions)
    moved = tuple(
        replace(
            t,
            pk=t.pk + offset,
            linked_pk=None if t.linked_pk is None else t.linked_pk + offset,
        )
        for t in second.transactions
    )
    return replace(first, transactions=(*first.transactions, *moved))


@pytest.fixture
def overlapping(
    tmp_path: Path, make_config: Callable[[str], Config]
) -> tuple[Config, Path, MoneyWizSnapshot, MoneyWizSnapshot]:
    """Month one holds round-ups of Aug 1-2, month two of Aug 2-3; each imported in turn."""
    config = make_config(ROUNDUPS_CONFIG)
    one = statement_month(tmp_path, "one", MONTH_ONE)
    two = statement_month(tmp_path, "two", MONTH_TWO)
    after_one = imported_snapshot(run_convert(one, config, dry_run=True), ROUNDUP_OPENINGS)
    converted_two = run_convert(two, config, dry_run=True, snapshot=after_one)
    assert [len(lump.rows) for lump in converted_two.lumps] == [1]
    assert len(converted_two.files[0].skipped) == 1
    after_two = stacked(after_one, imported_snapshot(converted_two))
    return config, two, after_one, after_two


def test_an_earlier_lump_of_overlapping_statements_is_not_extra(
    overlapping: tuple[Config, Path, MoneyWizSnapshot, MoneyWizSnapshot],
) -> None:
    config, two, _, after_two = overlapping

    result = run_verify(two, config, after_two)

    assert (result.missing, result.wrong, result.extra) == ((), (), ())
    assert all(e.unexplained == 0 for e in result.balances)
    assert result.clean is True


def test_only_the_rows_after_the_newest_lump_are_missing(
    overlapping: tuple[Config, Path, MoneyWizSnapshot, MoneyWizSnapshot],
) -> None:
    config, two, after_one, _ = overlapping

    result = run_verify(two, config, after_one)

    (item,) = result.missing
    assert (item.day, item.account, item.amount) == (
        datetime(2026, 8, 3).date(),
        "Shared -> Travel",
        Decimal("-0.30"),
    )
    assert "roundups lump of 1 row" in item.description
    assert (result.wrong, result.extra) == ((), ())
    assert entry(result, "Shared").missing == Decimal("-0.30")
    assert all(e.unexplained == 0 for e in result.balances)


# --- balance explanations stop at the balance day ------------------------------------------

LATE_PENDING = "Card Payment,Current,2026-08-04 09:00:00,,Late Shop,-5.00,0.00,EUR,PENDING,"


def test_rows_after_the_balance_day_do_not_explain_it(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)
    (roundups_folder / "revolut_shared.csv").write_text(ROUNDUPS_CSV + "\n" + LATE_PENDING)
    snapshot = imported_snapshot(
        run_convert(roundups_folder, config, dry_run=True), ROUNDUP_OPENINGS
    )
    travel = next(a for a in snapshot.accounts if a.name == "Travel")
    late = replace(
        snapshot.transactions[0],
        pk=9000,
        kind="deposit",
        account="Travel",
        account_pk=travel.pk,
        amount=Decimal("7.00"),
        date=datetime(2026, 8, 4, 12, 0),
        notes="",
        other_account=None,
        other_account_pk=None,
        linked_pk=None,
    )

    result = run_verify(
        roundups_folder, config, replace(snapshot, transactions=(*snapshot.transactions, late))
    )

    assert [i.transaction.pk for i in result.extra] == [9000]
    shared, travel_entry = entry(result, "Shared"), entry(result, "Travel")
    assert shared.day == travel_entry.day == datetime(2026, 8, 3).date()
    assert (shared.pending, shared.unexplained) == (0, 0)
    assert (travel_entry.extra, travel_entry.unexplained) == (0, 0)


def test_a_missing_row_after_the_balance_day_does_not_explain_it(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)
    (roundups_folder / "revolut_shared.csv").write_text(ROUNDUPS_CSV + "\n" + LATE_PENDING)
    snapshot = imported_snapshot(
        run_convert(roundups_folder, config, dry_run=True), ROUNDUP_OPENINGS
    )
    late = find(snapshot, "Shared", "-5.00")

    result = run_verify(roundups_folder, config, without(snapshot, late.pk))

    (item,) = result.missing
    assert item.day == datetime(2026, 8, 4).date()
    shared = entry(result, "Shared")
    assert (shared.missing, shared.unexplained) == (0, 0)


# --- report --------------------------------------------------------------------------------


def rendered(result: VerifyResult) -> str:
    console = Console(record=True, width=200)
    render_verify_report(result, console)
    return console.export_text()


def test_a_pending_explained_balance_is_nothing_to_fix(
    statement_folder: Path, config: Config
) -> None:
    converted = run_convert(statement_folder, config, dry_run=True)
    snapshot = imported_snapshot(converted, {**OPENINGS, "Shared": Decimal("100.00")})

    output = rendered(run_verify(statement_folder, config, snapshot))

    assert "explained" in output
    assert "Nothing to fix" in output


def test_a_missing_round_up_lump_shows_both_accounts(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)
    snapshot = imported_snapshot(
        run_convert(roundups_folder, config, dry_run=True), ROUNDUP_OPENINGS
    )
    lump = next(t for t in snapshot.transactions if "smt-lump:" in t.notes)
    assert lump.linked_pk is not None

    output = rendered(
        run_verify(roundups_folder, config, without(snapshot, lump.pk, lump.linked_pk))
    )

    assert "Shared -> Travel" in output


# --- inconsistent statements ----------------------------------------------------------------


def test_a_statement_whose_balance_does_not_add_up_is_reported(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)
    (roundups_folder / "revolut_shared.csv").write_text(ROUNDUPS_CSV.replace("96.40", "96.41"))
    converted = run_convert(roundups_folder, config, dry_run=True)
    assert converted.mismatched

    result = run_verify(roundups_folder, config, imported_snapshot(converted, ROUNDUP_OPENINGS))

    (problem,) = result.inconsistent
    assert problem.file.name == "revolut_shared.csv"
    assert "running balance" in problem.problem
    assert result.clean is False
    output = rendered(result)
    assert "revolut_shared.csv" in output
    assert "Nothing to fix" not in output


def test_a_statement_with_a_row_accounting_gap_is_reported(
    statement_folder: Path,
    config: Config,
    imported: tuple[ConvertResult, MoneyWizSnapshot],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inflate_wise_input_rows(monkeypatch)

    result = run_verify(statement_folder, config, imported[1])

    (problem,) = result.inconsistent
    assert problem.file.name == "wise.csv"
    assert "row accounting" in problem.problem
    assert (result.missing, result.wrong, result.extra) == ((), (), ())
    assert result.clean is False


def test_a_moneywiz_row_on_the_statements_first_day_is_not_extra(
    statement_folder: Path, config: Config, imported: tuple[ConvertResult, MoneyWizSnapshot]
) -> None:
    _, snapshot = imported
    coffee = find(snapshot, "Shared", "-3.50")
    first_day = min(t.date for t in snapshot.transactions if t.account == "Shared").date()
    early = replace(
        coffee,
        pk=9000,
        notes="",
        amount=Decimal("-41.00"),
        date=datetime(first_day.year, first_day.month, first_day.day, 0, 30),
    )

    result = run_verify(
        statement_folder, config, replace(snapshot, transactions=(*snapshot.transactions, early))
    )

    assert result.extra == ()


def test_pending_rows_alone_explain_a_difference_despite_an_unrelated_extra_row(
    statement_folder: Path, config: Config
) -> None:
    result = run_convert(statement_folder, config, dry_run=True)
    snapshot = imported_snapshot(result, {**OPENINGS, "Shared": Decimal("100.00")})
    shared = entry(run_verify(statement_folder, config, snapshot), "Shared")

    polluted = replace(shared, extra=Decimal("-48.61"))

    assert polluted.unexplained != 0
    assert polluted.pending_explains is True
    assert polluted.agrees is True
