import random
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from smoothment.classify.model import ClassifiedRow
from smoothment.config import TransferSettings
from smoothment.export import assign_tags, lump_tag, memo_tag
from smoothment.link import Transfer
from smoothment.lumps import Lump
from smoothment.moneywiz.model import Account, MoneyWizSnapshot, Transaction, TransactionKind
from smoothment.reconcile import (
    LumpUnit,
    PlainUnit,
    TransferUnit,
    Unit,
    lump_cutoffs,
    reconcile,
)
from tests.classify_fixtures import make_row

SETTINGS = TransferSettings()
BLACK, SAFETY, THIRD = 1, 2, 3


def account(pk: int, name: str) -> Account:
    return Account(
        pk=pk,
        name=name,
        currency="EUR",
        kind="bank",
        opening_balance=Decimal(0),
        archived=False,
    )


def snapshot(
    *transactions: Transaction, accounts: tuple[Account, ...] | None = None
) -> MoneyWizSnapshot:
    return MoneyWizSnapshot(
        accounts=accounts
        or (account(BLACK, "Black"), account(SAFETY, "Safety"), account(THIRD, "Third")),
        categories=(),
        payees=(),
        transactions=transactions,
    )


def tx(
    pk: int,
    *,
    account_pk: int = BLACK,
    amount: str = "-10.00",
    day: int = 1,
    kind: TransactionKind | None = None,
    notes: str = "",
    other_account_pk: int | None = None,
    linked_pk: int | None = None,
) -> Transaction:
    value = Decimal(amount)
    return Transaction(
        pk=pk,
        kind=kind or ("deposit" if value > 0 else "withdraw"),
        account="x",
        account_pk=account_pk,
        amount=value,
        date=datetime(2026, 9, day, 1, 0, 0),
        description="",
        notes=notes,
        payee=None,
        other_account=None,
        categories=(),
        created=datetime(2026, 9, day, 1, 0, 0),
        status=0,
        other_account_pk=other_account_pk,
        linked_pk=linked_pk,
    )


def classified(**overrides: Any) -> ClassifiedRow:
    account_name = overrides.pop("classified_account", None)
    overrides.setdefault("account", "Black")
    row = make_row(**overrides)
    return ClassifiedRow(row=row, kind="purchase", evidence="test", account=account_name)


def transfer_unit(out: ClassifiedRow | None, inc: ClassifiedRow | None) -> TransferUnit:
    return TransferUnit(
        Transfer(
            outgoing=out,
            incoming=inc,
            source="Black",
            destination="Safety",
            note="paired",
        )
    )


def run(units: list[Unit], snap: MoneyWizSnapshot, tags: dict[int, str] | None = None):
    return reconcile(units, tags or {}, snap, SETTINGS)


def tag_of(row: ClassifiedRow) -> str:
    return memo_tag(row.row)


# --- tag pass ----------------------------------------------------------------


def test_tag_hit_on_plain_row() -> None:
    row = classified(line=1)
    result = run([PlainUnit(row)], snapshot(tx(10, notes=f"note {tag_of(row)}", day=20)))
    assert [(m.transaction.pk, m.how, m.leg) for m in result.matches] == [(10, "tag", None)]
    assert result.remaining == ()
    assert result.consumed == frozenset({10})


def test_tag_comes_from_the_tags_mapping_when_present() -> None:
    row = classified(line=1)
    other = classified(line=2)
    tags = {id(row.row): "smt:aaaaaaaaaaaa", id(other.row): "smt:bbbbbbbbbbbb"}
    result = run(
        [PlainUnit(row), PlainUnit(other)],
        snapshot(tx(10, notes="smt:bbbbbbbbbbbb", day=20)),
        tags,
    )
    assert [m.unit for m in result.matches] == [PlainUnit(other)]
    assert result.remaining == (PlainUnit(row),)


def test_tag_hit_through_the_merged_leg() -> None:
    out = classified(account="Black", amount=Decimal("-50.00"), line=1)
    inc = classified(account="Safety", amount=Decimal("50.00"), line=2)
    unit = transfer_unit(out, inc)
    transaction = tx(
        10,
        account_pk=SAFETY,
        amount="50.00",
        day=20,
        kind="transfer_in",
        notes=f"{tag_of(inc)}",
    )
    result = run([unit], snapshot(transaction))
    (match,) = result.matches
    assert match.how == "tag"
    assert match.leg is inc


def test_tag_match_with_both_tags_picks_the_leg_by_transaction_kind() -> None:
    out = classified(account="Black", amount=Decimal("-50.00"), line=1)
    inc = classified(account="Safety", amount=Decimal("50.00"), line=2)
    notes = f"{tag_of(out)} {tag_of(inc)}"
    unit = transfer_unit(out, inc)
    as_out = tx(10, amount="-50.00", kind="transfer_out", notes=notes, linked_pk=11)
    as_in = tx(11, account_pk=SAFETY, amount="50.00", kind="transfer_in", notes=notes)
    (match,) = run([unit], snapshot(as_out, as_in)).matches
    assert match.leg is out
    assert match.transaction.pk == 10
    (match,) = run([unit], snapshot(as_in)).matches
    assert match.leg is inc


def test_tag_match_of_a_transfer_consumes_the_linked_leg() -> None:
    out = classified(account="Black", amount=Decimal("-50.00"), line=1)
    unit = transfer_unit(out, None)
    as_out = tx(10, amount="-50.00", kind="transfer_out", notes=tag_of(out), linked_pk=11)
    as_in = tx(11, account_pk=SAFETY, amount="50.00", kind="transfer_in", linked_pk=10)
    lone_in = classified(account="Safety", amount=Decimal("50.00"), line=2)
    result = run([unit, PlainUnit(lone_in)], snapshot(as_out, as_in))
    assert result.consumed == frozenset({10, 11})
    assert result.remaining == (PlainUnit(lone_in),)


def test_lump_matches_by_tag_only() -> None:
    lump = make_lump()
    notes = f"{lump_tag(lump)} smt-lump:{lump.key}:20260920T100000"
    result = run([LumpUnit(lump)], snapshot(tx(10, amount="-1.50", day=20, notes=notes)))
    assert [(m.transaction.pk, m.how, m.leg) for m in result.matches] == [(10, "tag", None)]


def test_lump_without_a_tag_never_matches_fuzzily() -> None:
    lump = make_lump()
    result = run([LumpUnit(lump)], snapshot(tx(10, amount="-1.50", day=20)))
    assert result.matches == ()
    assert result.remaining == (LumpUnit(lump),)


def make_lump(**overrides: Any) -> Lump:
    row = classified(line=1, amount=Decimal("-1.50"))
    defaults: dict[str, Any] = dict(
        kind="fee",
        bank="revolut",
        account="Black",
        source_account="Black",
        key="0123abcd",
        counterpart=None,
        pocket=None,
        amount=Decimal("-1.50"),
        date=date(2026, 9, 20),
        cutoff=datetime(2026, 9, 20, 10, 0, 0),
        first=date(2026, 9, 1),
        rows=(row,),
        payee=None,
    )
    defaults.update(overrides)
    return Lump(**defaults)


# --- fuzzy pass --------------------------------------------------------------


@pytest.mark.parametrize(
    ("tx_day", "matched"),
    [(10, True), (9, True), (11, True), (8, False), (12, False)],
)
def test_fuzzy_window_for_a_plain_row_is_one_day(tx_day: int, matched: bool) -> None:
    row = classified(date=datetime(2026, 9, 10, 15, 0, 0), amount=Decimal("-10.00"))
    result = run([PlainUnit(row)], snapshot(tx(10, day=tx_day)))
    assert bool(result.matches) is matched
    assert (result.remaining == ()) is matched
    if matched:
        assert result.matches[0].how == "fuzzy"


def test_one_cent_difference_does_not_match() -> None:
    row = classified(amount=Decimal("-10.01"))
    assert run([PlainUnit(row)], snapshot(tx(10, amount="-10.00"))).matches == ()


def test_opposite_sign_does_not_match() -> None:
    row = classified(amount=Decimal("10.00"))
    assert run([PlainUnit(row)], snapshot(tx(10, amount="-10.00"))).matches == ()


def test_other_account_does_not_match() -> None:
    row = classified(account="Safety")
    assert run([PlainUnit(row)], snapshot(tx(10, account_pk=BLACK))).matches == ()


def test_classified_account_overrides_the_row_account() -> None:
    row = classified(account="Black", classified_account="Safety")
    result = run([PlainUnit(row)], snapshot(tx(10, account_pk=SAFETY)))
    assert len(result.matches) == 1


def test_unknown_account_has_no_candidates() -> None:
    row = classified(account="Nowhere")
    result = run([PlainUnit(row)], snapshot(tx(10)))
    assert result.matches == ()
    assert result.remaining == (PlainUnit(row),)


def test_account_names_compare_with_nbsp_and_case_normalised() -> None:
    row = classified(account="BLACK\xa0 card")
    snap = snapshot(tx(10), accounts=(account(BLACK, "Black card"),))
    assert len(run([PlainUnit(row)], snap).matches) == 1


def test_three_identical_purchases_against_two_leave_the_third() -> None:
    rows = [classified(line=n, date=datetime(2026, 9, n, 12, 0, 0)) for n in (1, 2, 3)]
    result = run(
        [PlainUnit(r) for r in rows],
        snapshot(tx(10, day=1), tx(11, day=2)),
    )
    assert result.remaining == (PlainUnit(rows[2]),)
    assert sorted(m.transaction.pk for m in result.matches) == [10, 11]


def test_one_row_for_two_candidates_matches_exactly_one_deterministically() -> None:
    early = classified(line=1, date=datetime(2026, 9, 9, 12, 0, 0))
    exact = classified(line=2, date=datetime(2026, 9, 10, 12, 0, 0))
    units: list[Unit] = [PlainUnit(early), PlainUnit(exact)]
    snap = snapshot(tx(10, day=10))
    result = run(units, snap)
    assert len(result.matches) == 1
    assert len(result.remaining) == 1
    assert run(units[::-1], snap) == result


def test_tagged_moneywiz_row_is_not_a_fuzzy_candidate() -> None:
    row = classified(line=1)
    other_tag = "smt:ffffffffffff"
    result = run([PlainUnit(row)], snapshot(tx(10, notes=other_tag)))
    assert result.matches == ()
    assert result.consumed == frozenset()


def test_reconcile_rows_are_not_fuzzy_candidates() -> None:
    row = classified(line=1)
    result = run([PlainUnit(row)], snapshot(tx(10, kind="reconcile")))
    assert result.matches == ()


def test_a_tag_match_is_not_stolen_by_the_fuzzy_pass() -> None:
    tagged = classified(line=1, date=datetime(2026, 9, 5, 12, 0, 0))
    plain = classified(line=2, date=datetime(2026, 9, 5, 12, 0, 0))
    first = tx(10, day=5, notes=tag_of(tagged))
    second = tx(11, day=5)
    result = run([PlainUnit(plain), PlainUnit(tagged)], snapshot(first, second))
    by_unit = {m.unit: m for m in result.matches}
    assert by_unit[PlainUnit(tagged)].transaction.pk == 10
    assert by_unit[PlainUnit(plain)].transaction.pk == 11
    assert by_unit[PlainUnit(plain)].how == "fuzzy"


# --- transfers ---------------------------------------------------------------


def test_transfer_matches_through_its_incoming_leg_alone() -> None:
    inc = classified(account="Safety", amount=Decimal("50.00"), line=2)
    unit = transfer_unit(None, inc)
    transaction = tx(
        10, account_pk=SAFETY, amount="50.00", kind="transfer_in", other_account_pk=BLACK
    )
    (match,) = run([unit], snapshot(transaction)).matches
    assert match.how == "fuzzy"
    assert match.leg is inc


def test_outgoing_leg_expects_the_destination_as_counterpart() -> None:
    out = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 10, 12, 0, 0)
    )
    unit = transfer_unit(out, None)
    right = tx(10, day=13, amount="-50.00", kind="transfer_out", other_account_pk=SAFETY)
    wrong = tx(10, day=13, amount="-50.00", kind="transfer_out", other_account_pk=THIRD)
    assert [m.transaction.pk for m in run([unit], snapshot(right)).matches] == [10]
    assert run([unit], snapshot(wrong)).matches == ()


def test_transfer_leg_three_days_off_does_not_match_a_plain_row() -> None:
    out = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 10, 12, 0, 0)
    )
    unit = transfer_unit(out, None)
    assert run([unit], snapshot(tx(10, day=13, amount="-50.00"))).matches == ()


def test_transfer_leg_one_day_off_may_match_a_plain_row() -> None:
    out = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 10, 12, 0, 0)
    )
    unit = transfer_unit(out, None)
    (match,) = run([unit], snapshot(tx(10, day=11, amount="-50.00"))).matches
    assert match.transaction.kind == "withdraw"


def test_window_days_governs_transfer_legs() -> None:
    out = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 10, 12, 0, 0)
    )
    unit = transfer_unit(out, None)
    snap = snapshot(tx(10, day=15, amount="-50.00", kind="transfer_out", other_account_pk=SAFETY))
    assert reconcile([unit], {}, snap, TransferSettings(window_days=5)).matches
    assert not reconcile([unit], {}, snap, TransferSettings(window_days=4)).matches


def test_matching_a_transfer_consumes_both_moneywiz_legs() -> None:
    out = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 10, 12, 0, 0), line=1
    )
    inc = classified(
        account="Safety", amount=Decimal("50.00"), date=datetime(2026, 9, 10, 12, 0, 0), line=2
    )
    unit = transfer_unit(out, inc)
    as_out = tx(
        10, amount="-50.00", day=10, kind="transfer_out", other_account_pk=SAFETY, linked_pk=11
    )
    as_in = tx(
        11,
        account_pk=SAFETY,
        amount="50.00",
        day=10,
        kind="transfer_in",
        other_account_pk=BLACK,
        linked_pk=10,
    )
    lone = classified(
        account="Safety", amount=Decimal("50.00"), date=datetime(2026, 9, 10, 12, 0, 0), line=3
    )
    third = tx(12, account_pk=SAFETY, amount="50.00", day=10)
    result = run([unit, PlainUnit(lone)], snapshot(as_out, as_in, third))
    by_unit = {m.unit: m for m in result.matches}
    assert by_unit[unit].transaction.pk in {10, 11}
    assert {10, 11} <= result.consumed
    assert by_unit[PlainUnit(lone)].transaction.pk == 12


def test_transfer_unit_matches_once_even_with_two_candidate_legs() -> None:
    out = classified(account="Black", amount=Decimal("-50.00"), line=1)
    inc = classified(account="Safety", amount=Decimal("50.00"), line=2)
    unit = transfer_unit(out, inc)
    as_out = tx(10, amount="-50.00", kind="transfer_out", other_account_pk=SAFETY, linked_pk=11)
    as_in = tx(
        11,
        account_pk=SAFETY,
        amount="50.00",
        kind="transfer_in",
        other_account_pk=BLACK,
        linked_pk=10,
    )
    result = run([unit], snapshot(as_out, as_in))
    assert len(result.matches) == 1
    assert result.consumed == frozenset({10, 11})


# --- determinism -------------------------------------------------------------


def test_result_does_not_depend_on_input_order() -> None:
    rows = [
        classified(line=n, date=datetime(2026, 9, 1 + n % 3, 12, 0, 0), amount=Decimal("-10.00"))
        for n in range(1, 7)
    ]
    out = classified(account="Black", amount=Decimal("-50.00"), line=20)
    inc = classified(account="Safety", amount=Decimal("50.00"), line=21)
    units: list[Unit] = [PlainUnit(r) for r in rows] + [
        transfer_unit(out, inc),
        LumpUnit(make_lump()),
    ]
    snap = snapshot(
        tx(10, day=1),
        tx(11, day=2),
        tx(12, day=2),
        tx(13, day=3),
        tx(14, amount="-50.00", kind="transfer_out", other_account_pk=SAFETY, linked_pk=15),
        tx(15, account_pk=SAFETY, amount="50.00", kind="transfer_in", linked_pk=14),
    )
    expected = run(units, snap)
    rng = random.Random(7)
    for _ in range(20):
        shuffled = units[:]
        rng.shuffle(shuffled)
        assert run(shuffled, snap) == expected


def test_tags_mapping_from_assign_tags_is_honoured_for_identical_rows() -> None:
    first = classified(line=1)
    second = classified(line=2)
    tags = assign_tags([first.row, second.row])
    snap = snapshot(tx(10, day=20, notes=tags[id(second.row)]))
    result = run([PlainUnit(first), PlainUnit(second)], snap, tags)
    assert [m.unit for m in result.matches] == [PlainUnit(second)]


# --- lump cutoffs ------------------------------------------------------------


def test_lump_cutoffs_keeps_the_newest_per_key() -> None:
    snap = snapshot(
        tx(1, notes="smt:aaaaaaaaaaaa smt-lump:0123abcd:20260820T101500"),
        tx(2, notes="x smt-lump:0123abcd:20260920T090000 y"),
        tx(3, notes="smt-lump:0123abcd:20260910T090000"),
        tx(4, notes="smt-lump:deadbeef:20260101T000000"),
        tx(5, notes="nothing here"),
    )
    assert lump_cutoffs(snap) == {
        "0123abcd": datetime(2026, 9, 20, 9, 0, 0),
        "deadbeef": datetime(2026, 1, 1, 0, 0, 0),
    }


def test_lump_cutoffs_is_empty_without_markers() -> None:
    assert lump_cutoffs(snapshot(tx(1))) == {}


# --- fix round: sweeps, kind preference, unlinked legs -----------------------


def test_sweep_pairs_two_rows_that_are_each_one_day_late() -> None:
    rows = [
        classified(line=n, date=datetime(2026, 9, 9 + n, 12, 0, 0), amount=Decimal("-3.50"))
        for n in (1, 2)
    ]
    result = run(
        [PlainUnit(r) for r in rows],
        snapshot(tx(10, day=11, amount="-3.50"), tx(11, day=12, amount="-3.50")),
    )
    assert result.remaining == ()
    by_unit = {m.unit: m.transaction.pk for m in result.matches}
    assert by_unit == {PlainUnit(rows[0]): 10, PlainUnit(rows[1]): 11}
    assert result.consumed == frozenset({10, 11})


def scenario_transfer_and_cash() -> tuple[list[Unit], MoneyWizSnapshot]:
    out = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 10, 12, 0, 0), line=1
    )
    cash = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 10, 12, 0, 0), line=2
    )
    snap = snapshot(
        tx(10, day=10, amount="-50.00"),
        tx(11, day=10, amount="-50.00", kind="transfer_out", other_account_pk=SAFETY),
    )
    return [transfer_unit(out, None), PlainUnit(cash)], snap


def test_transfer_leg_takes_the_transfer_row_and_plain_row_the_plain_one() -> None:
    units, snap = scenario_transfer_and_cash()
    result = run(units, snap)
    by_kind = {type(m.unit): m.transaction.pk for m in result.matches}
    assert by_kind == {TransferUnit: 11, PlainUnit: 10}


def test_kind_preference_is_independent_of_input_order() -> None:
    units, snap = scenario_transfer_and_cash()
    expected = run(units, snap)
    rng = random.Random(3)
    for _ in range(10):
        shuffled = units[:]
        rng.shuffle(shuffled)
        assert run(shuffled, snap) == expected


def test_plain_row_nearer_in_time_does_not_take_the_transfer_row() -> None:
    out = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 10, 12, 0, 0), line=1
    )
    cash = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 11, 12, 0, 0), line=2
    )
    snap = snapshot(tx(11, day=12, amount="-50.00", kind="transfer_out", other_account_pk=SAFETY))
    result = run([PlainUnit(cash), transfer_unit(out, None)], snap)
    assert [type(m.unit) for m in result.matches] == [TransferUnit]
    assert result.remaining == (PlainUnit(cash),)


def two_leg_unit() -> tuple[TransferUnit, ClassifiedRow, ClassifiedRow]:
    out = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 10, 12, 0, 0), line=1
    )
    inc = classified(
        account="Safety", amount=Decimal("50.00"), date=datetime(2026, 9, 10, 12, 0, 0), line=2
    )
    return transfer_unit(out, inc), out, inc


def test_two_unlinked_plain_rows_are_both_consumed_by_a_transfer() -> None:
    unit, out, _ = two_leg_unit()
    snap = snapshot(
        tx(10, day=10, amount="-50.00"),
        tx(11, account_pk=SAFETY, day=11, amount="50.00"),
    )
    (match,) = run([unit], snap).matches
    assert match.transaction.pk == 10
    assert match.leg is out
    assert match.other is not None
    assert match.other.pk == 11
    assert run([unit], snap).consumed == frozenset({10, 11})


def test_other_leg_is_not_searched_when_the_matched_row_is_linked() -> None:
    unit, _, _ = two_leg_unit()
    snap = snapshot(
        tx(10, day=10, amount="-50.00", kind="transfer_out", other_account_pk=SAFETY, linked_pk=11),
        tx(11, account_pk=SAFETY, day=10, amount="50.00", kind="transfer_in", linked_pk=10),
        tx(12, account_pk=SAFETY, day=10, amount="50.00"),
    )
    result = run([unit], snap)
    assert result.matches[0].other is None
    assert result.consumed == frozenset({10, 11})


def test_other_leg_needs_its_own_account_and_a_close_date() -> None:
    unit, _, _ = two_leg_unit()
    snap = snapshot(
        tx(10, day=10, amount="-50.00"),
        tx(11, account_pk=THIRD, day=10, amount="50.00"),
        tx(12, account_pk=SAFETY, day=13, amount="50.00"),
    )
    result = run([unit], snap)
    assert result.matches[0].other is None
    assert result.consumed == frozenset({10})


def test_other_leg_found_after_a_tag_match_on_a_plain_row() -> None:
    unit, out, inc = two_leg_unit()
    snap = snapshot(
        tx(10, day=10, amount="-50.00", notes=tag_of(out)),
        tx(11, account_pk=SAFETY, day=10, amount="50.00", notes=tag_of(inc)),
    )
    (match,) = run([unit], snap).matches
    assert match.how == "tag"
    assert match.other is not None
    assert match.other.pk == 11


def test_tag_leg_follows_the_amount_sign_for_a_plain_row() -> None:
    unit, out, inc = two_leg_unit()
    notes = f"{tag_of(out)} {tag_of(inc)}"
    deposit = tx(10, account_pk=SAFETY, amount="50.00", notes=notes)
    (match,) = run([unit], snapshot(deposit)).matches
    assert match.leg is inc
    withdraw = tx(10, amount="-50.00", notes=notes)
    (match,) = run([unit], snapshot(withdraw)).matches
    assert match.leg is out


# --- lump marker parsing -----------------------------------------------------


@pytest.mark.parametrize(
    "notes",
    [
        "smt-lump:0123abcd:20261399T250000",
        "xsmt-lump:0123abcd:20260920T100000",
        "smt-lump:0123abcd:20260920T1000001",
        "smt-lump:0123abcd9:20260920T100000",
        "smt-lump:0123abcd:20260920T10000",
    ],
)
def test_lump_cutoffs_ignores_malformed_and_embedded_markers(notes: str) -> None:
    assert lump_cutoffs(snapshot(tx(1, notes=notes))) == {}


def test_lump_cutoffs_skips_a_bad_date_but_keeps_the_good_ones() -> None:
    snap = snapshot(
        tx(1, notes="smt-lump:0123abcd:20261399T250000"),
        tx(2, notes="smt-lump:0123abcd:20260920T100000"),
    )
    assert lump_cutoffs(snap) == {"0123abcd": datetime(2026, 9, 20, 10, 0, 0)}


def plain_on(day: int, line: int, account_name: str = "Black", amount: str = "-10.00") -> Unit:
    return PlainUnit(
        classified(
            account=account_name,
            line=line,
            amount=Decimal(amount),
            date=datetime(2026, 9, day, 12, 0, 0),
        )
    )


def out_leg_on(day: int, line: int) -> Unit:
    out = classified(
        account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, day, 12, 0, 0), line=line
    )
    return transfer_unit(out, None)


def transfer_out_on(pk: int, day: int) -> Transaction:
    return tx(pk, day=day, amount="-50.00", kind="transfer_out", other_account_pk=SAFETY)


def test_plain_rows_get_the_largest_matching() -> None:
    units = [plain_on(4, 1), plain_on(4, 2), plain_on(5, 3)]
    result = run(units, snapshot(tx(10, day=5), tx(11, day=5), tx(12, day=6)))
    assert result.remaining == ()
    assert result.consumed == frozenset({10, 11, 12})


def test_transfer_legs_get_the_largest_matching() -> None:
    units = [out_leg_on(4, 1), out_leg_on(4, 2), out_leg_on(6, 3)]
    snap = snapshot(transfer_out_on(10, 7), transfer_out_on(11, 7), transfer_out_on(12, 9))
    result = run(units, snap)
    assert result.remaining == ()
    assert result.consumed == frozenset({10, 11, 12})


def _maximum_matching(
    days: list[int], store_days: list[int], window: int, taken: frozenset[int] = frozenset()
) -> int:
    if not days:
        return 0
    first, rest = days[0], days[1:]
    best = _maximum_matching(rest, store_days, window, taken)
    for index, day in enumerate(store_days):
        if index not in taken and abs(day - first) <= window:
            best = max(best, 1 + _maximum_matching(rest, store_days, window, taken | {index}))
    return best


@pytest.mark.parametrize("kind", ["plain", "transfer"])
def test_sweep_finds_a_maximum_matching_on_random_groups(kind: str) -> None:
    rng = random.Random(11)
    window = 1 if kind == "plain" else SETTINGS.window_days
    last = 3 * window + 1
    for _ in range(300):
        days = [rng.randint(1, last) for _ in range(rng.randint(1, 5))]
        store_days = [rng.randint(1, last) for _ in range(rng.randint(1, 5))]
        if kind == "plain":
            units = [plain_on(day, line) for line, day in enumerate(days, start=1)]
            snap = snapshot(*(tx(100 + i, day=day) for i, day in enumerate(store_days)))
        else:
            units = [out_leg_on(day, line) for line, day in enumerate(days, start=1)]
            snap = snapshot(*(transfer_out_on(100 + i, day) for i, day in enumerate(store_days)))
        expected = _maximum_matching(days, store_days, window)
        assert len(run(units, snap).matches) == expected, (days, store_days)


def test_a_plain_row_on_a_linked_transfer_leaves_the_other_leg_free() -> None:
    black = plain_on(10, 1)
    safety = plain_on(10, 2, account_name="Safety", amount="10.00")
    snap = snapshot(
        tx(10, day=10, kind="transfer_out", other_account_pk=SAFETY, linked_pk=11),
        tx(
            11,
            account_pk=SAFETY,
            amount="10.00",
            day=10,
            kind="transfer_in",
            other_account_pk=BLACK,
            linked_pk=10,
        ),
    )
    result = run([black, safety], snap)
    assert {m.unit: m.transaction.pk for m in result.matches} == {black: 10, safety: 11}
    assert result.consumed == frozenset({10, 11})


def test_equal_rows_from_different_banks_order_deterministically() -> None:
    first = classified(line=1, bank="revolut")
    second = classified(line=1, bank="wise")
    snap = snapshot(tx(10), tx(11))
    expected = run([PlainUnit(first), PlainUnit(second)], snap)
    assert run([PlainUnit(second), PlainUnit(first)], snap) == expected


def test_tag_on_both_moneywiz_legs_reports_the_leg_in_the_statement_legs_account() -> None:
    inc = classified(account="Safety", amount=Decimal("50.00"), line=2)
    unit = transfer_unit(None, inc)
    note = tag_of(inc)
    out_side = tx(
        10,
        account_pk=BLACK,
        amount="-50.00",
        day=20,
        kind="transfer_out",
        notes=note,
        other_account_pk=SAFETY,
        linked_pk=11,
    )
    in_side = tx(
        11,
        account_pk=SAFETY,
        amount="50.00",
        day=20,
        kind="transfer_in",
        notes=note,
        other_account_pk=BLACK,
        linked_pk=10,
    )
    result = run([unit], snapshot(out_side, in_side))
    (match,) = result.matches
    assert match.how == "tag"
    assert match.leg is inc
    assert match.transaction is in_side
    assert result.consumed == {10, 11}
