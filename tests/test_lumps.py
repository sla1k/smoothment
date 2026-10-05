import random
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from smoothment.classify.model import ClassifiedRow, RowKind
from smoothment.config import BankSettings, Config, PocketSettings
from smoothment.lumps import build_lumps, lump_key
from tests.classify_fixtures import make_config, make_row


def roundup(
    *, account: str = "Shared", pocket: str = "Travel", amount: str, line: int, day: int = 1
) -> ClassifiedRow:
    """A pocket_move row: the main-account leg of a pocket move, evidenced against `pocket`."""
    row = make_row(
        account=account,
        pocket=pocket,
        pocket_side=False,
        amount=Decimal(amount),
        line=line,
        date=datetime(2026, 9, day, 10, 0, 0),
    )
    return ClassifiedRow(row=row, kind="pocket_move", evidence="test", counterpart=pocket)


def pocket_income_row(
    *,
    main_account: str = "Shared",
    pocket_account: str,
    pocket: str,
    amount: str,
    line: int,
    bank: str = "revolut",
    day: int = 1,
) -> ClassifiedRow:
    """A pocket_income row: booked in `pocket_account`, distinct from the leg's own account."""
    row = make_row(
        account=main_account,
        bank=bank,
        pocket=pocket,
        pocket_side=True,
        amount=Decimal(amount),
        line=line,
        date=datetime(2026, 9, day, 10, 0, 0),
    )
    return ClassifiedRow(row=row, kind="pocket_income", evidence="test", account=pocket_account)


def savings_row(
    *,
    kind: RowKind,
    account: str = "Savings",
    amount: str,
    line: int,
    bank: str = "revolut",
    day: int = 1,
) -> ClassifiedRow:
    """A `fee`/`interest` row of a savings statement."""
    row = make_row(
        account=account,
        bank=bank,
        kind="savings",
        amount=Decimal(amount),
        line=line,
        date=datetime(2026, 9, day, 10, 0, 0),
    )
    return ClassifiedRow(row=row, kind=kind, evidence="test")


def larger_pocket_move(
    *, account: str = "Shared", pocket: str = "Travel", amount: str, line: int, day: int = 1
) -> ClassifiedRow:
    return roundup(account=account, pocket=pocket, amount=amount, line=line, day=day)


def default_config(**overrides: Any) -> Config:
    return make_config(**overrides)


# --- Round-ups ----------------------------------------------------------------


def test_three_roundups_merge_and_larger_move_passes_through() -> None:
    rows = [
        roundup(amount="0.10", line=1),
        roundup(amount="0.20", line=2),
        roundup(amount="0.30", line=3),
        larger_pocket_move(amount="5.00", line=4),
    ]
    lumps, individual, _covered = build_lumps(rows, default_config())

    assert len(lumps) == 1
    lump = lumps[0]
    assert lump.kind == "roundups"
    assert lump.amount == Decimal("0.60")
    assert lump.account == "Shared"
    assert lump.pocket == "Travel"
    assert lump.counterpart == "Travel"
    assert lump.payee is None
    assert len(lump.rows) == 3

    assert len(individual) == 1
    assert individual[0].row.amount == Decimal("5.00")


def test_roundups_net_in_both_directions() -> None:
    rows = [
        roundup(amount="0.30", line=1),
        roundup(amount="-0.10", line=2),
        roundup(amount="0.05", line=3),
    ]
    lumps, individual, _covered = build_lumps(rows, default_config())

    assert len(lumps) == 1
    assert lumps[0].amount == Decimal("0.25")
    assert individual == ()


def test_two_pockets_give_two_lumps() -> None:
    rows = [
        roundup(pocket="Travel", amount="0.10", line=1),
        roundup(pocket="Travel", amount="0.20", line=2),
        roundup(pocket="Food", amount="0.05", line=3),
        roundup(pocket="Food", amount="0.05", line=4),
    ]
    lumps, individual, _covered = build_lumps(rows, default_config())

    assert len(lumps) == 2
    assert individual == ()
    by_pocket = {lump.pocket: lump for lump in lumps}
    assert by_pocket["Travel"].amount == Decimal("0.30")
    assert by_pocket["Food"].amount == Decimal("0.10")


def test_threshold_inclusive_at_default_one_euro() -> None:
    rows = [
        roundup(amount="1.00", line=1),
        larger_pocket_move(amount="1.01", line=2),
    ]
    lumps, individual, _covered = build_lumps(rows, default_config())

    assert len(lumps) == 1
    assert lumps[0].amount == Decimal("1.00")
    assert len(individual) == 1
    assert individual[0].row.amount == Decimal("1.01")


def test_threshold_respects_configured_roundup_max() -> None:
    config = default_config(pockets=PocketSettings(roundup_max=Decimal("0.50")))
    rows = [
        roundup(amount="0.50", line=1),
        larger_pocket_move(amount="0.60", line=2),
    ]
    lumps, individual, _covered = build_lumps(rows, config)

    assert len(lumps) == 1
    assert lumps[0].amount == Decimal("0.50")
    assert len(individual) == 1
    assert individual[0].row.amount == Decimal("0.60")


def test_zero_sum_roundup_group_produces_no_lump() -> None:
    rows = [
        roundup(amount="0.10", line=1),
        roundup(amount="-0.10", line=2),
    ]
    lumps, individual, _covered = build_lumps(rows, default_config())

    assert lumps == ()
    assert len(individual) == 2
    assert {cr.row.line for cr in individual} == {1, 2}


def test_lump_is_still_produced_for_a_single_row_group() -> None:
    rows = [roundup(amount="0.07", line=1)]
    lumps, individual, _covered = build_lumps(rows, default_config())

    assert len(lumps) == 1
    assert lumps[0].amount == Decimal("0.07")
    assert len(lumps[0].rows) == 1
    assert individual == ()


# --- Pocket interest ------------------------------------------------------------


def test_pocket_interest_lump_lands_in_pocket_account_with_bank_payee() -> None:
    config = default_config(banks={"revolut": BankSettings(payee="Revolut")})
    rows = [
        pocket_income_row(pocket_account="Travel", pocket="Travel", amount="0.01", line=1),
        pocket_income_row(pocket_account="Travel", pocket="Travel", amount="0.01", line=2),
    ]
    lumps, individual, _covered = build_lumps(rows, config)

    assert len(lumps) == 1
    lump = lumps[0]
    assert lump.kind == "interest"
    assert lump.account == "Travel"
    assert lump.pocket == "Travel"
    assert lump.payee == "Revolut"
    assert lump.counterpart is None
    assert lump.amount == Decimal("0.02")
    assert individual == ()
    # the row's own account is the main account, not the pocket's booking account
    assert all(cr.row.account == "Shared" for cr in lump.rows)


def test_pocket_interest_groups_by_pocket_account_not_row_account() -> None:
    config = default_config(banks={"revolut": BankSettings(payee="Revolut")})
    rows = [
        pocket_income_row(pocket_account="Travel", pocket="Travel", amount="0.01", line=1),
        pocket_income_row(pocket_account="Food", pocket="Food", amount="0.02", line=2),
    ]
    lumps, individual, _covered = build_lumps(rows, config)

    assert len(lumps) == 2
    assert individual == ()
    by_account = {lump.account: lump for lump in lumps}
    assert by_account["Travel"].amount == Decimal("0.01")
    assert by_account["Food"].amount == Decimal("0.02")


# --- Savings interest and fees ---------------------------------------------------


def test_savings_interest_sums_and_rounds() -> None:
    config = default_config(banks={"revolut": BankSettings(payee="Revolut")})
    rows = [
        savings_row(kind="interest", amount="0.1272", line=1),
        savings_row(kind="interest", amount="0.1272", line=2),
        savings_row(kind="interest", amount="0.1272", line=3),
    ]
    lumps, individual, _covered = build_lumps(rows, config)

    assert len(lumps) == 1
    lump = lumps[0]
    assert lump.kind == "interest"
    assert lump.account == "Savings"
    assert lump.pocket is None
    assert lump.amount == Decimal("0.38")
    assert lump.payee == "Revolut"
    assert individual == ()


def test_savings_fees_sum_and_round() -> None:
    config = default_config(banks={"revolut": BankSettings(payee="Revolut")})
    rows = [
        savings_row(kind="fee", amount="-0.0072", line=1),
        savings_row(kind="fee", amount="-0.0072", line=2),
        savings_row(kind="fee", amount="-0.0072", line=3),
    ]
    lumps, individual, _covered = build_lumps(rows, config)

    assert len(lumps) == 1
    lump = lumps[0]
    assert lump.kind == "fee"
    assert lump.account == "Savings"
    assert lump.amount == Decimal("-0.02")
    assert lump.payee == "Revolut"
    assert individual == ()


def test_non_savings_interest_and_fee_rows_pass_through() -> None:
    row_interest = make_row(kind="current", amount=Decimal("0.05"), line=1)
    row_fee = make_row(kind="current", amount=Decimal("-15.99"), line=2)
    interest_row = ClassifiedRow(row=row_interest, kind="interest", evidence="test")
    fee_row = ClassifiedRow(row=row_fee, kind="fee", evidence="test")

    lumps, individual, _covered = build_lumps([interest_row, fee_row], default_config())

    assert lumps == ()
    assert individual == (interest_row, fee_row)


# --- date / first ---------------------------------------------------------------


def test_lump_date_and_first_are_first_and_last_merged_row_dates() -> None:
    rows = [
        roundup(amount="0.10", line=1, day=5),
        roundup(amount="0.10", line=2, day=1),
        roundup(amount="0.10", line=3, day=10),
    ]
    lumps, _individual, _covered = build_lumps(rows, default_config())

    assert len(lumps) == 1
    assert lumps[0].first == date(2026, 9, 1)
    assert lumps[0].date == date(2026, 9, 10)


# --- Other kinds untouched --------------------------------------------------------


def test_other_kinds_pass_through_untouched() -> None:
    def simple(kind: RowKind, amount: str, line: int) -> ClassifiedRow:
        row = make_row(amount=Decimal(amount), line=line)
        return ClassifiedRow(row=row, kind=kind, evidence="test")

    purchase = simple("purchase", "-3.50", 1)
    income = simple("income", "100.00", 2)
    excluded_row = make_row(amount=Decimal("1.00"), line=3)
    excluded = ClassifiedRow(row=excluded_row, kind="excluded", evidence="test", reason="reverted")

    lumps, individual, _covered = build_lumps([purchase, income, excluded], default_config())

    assert lumps == ()
    assert individual == (purchase, income, excluded)


# --- Input order independence -----------------------------------------------------


def test_input_order_does_not_change_the_result() -> None:
    rows: list[ClassifiedRow] = [
        roundup(pocket="Travel", amount="0.10", line=1, day=1),
        roundup(pocket="Travel", amount="0.20", line=2, day=2),
        roundup(pocket="Food", amount="0.05", line=3, day=1),
        savings_row(kind="interest", amount="0.1272", line=5),
        savings_row(kind="interest", amount="0.1272", line=6),
    ]
    passthrough_row = make_row(kind="current", amount=Decimal("-3.50"), line=4)
    passthrough = ClassifiedRow(row=passthrough_row, kind="purchase", evidence="test")
    rows.insert(3, passthrough)

    shuffled = rows[:]
    random.Random(42).shuffle(shuffled)
    assert [cr.row.line for cr in shuffled] != [cr.row.line for cr in rows]

    lumps_a, individual_a, _covered = build_lumps(rows, default_config())
    lumps_b, individual_b, _covered = build_lumps(shuffled, default_config())

    assert lumps_a == lumps_b
    assert {cr.row.line for cr in individual_a} == {cr.row.line for cr in individual_b} == {4}
    # individual rows keep each call's own input order
    assert [cr.row.line for cr in individual_a] == [4]


# --- source account, key, cutoff ----------------------------------------------------


def test_lump_records_the_statement_account_key_and_latest_timestamp() -> None:
    rows = [
        roundup(amount="0.10", line=1, day=5),
        roundup(amount="0.10", line=2, day=9),
        roundup(amount="0.10", line=3, day=2),
    ]

    (lump,), _, _covered = build_lumps(rows, default_config())

    assert lump.source_account == "Shared"
    assert lump.cutoff == datetime(2026, 9, 9, 10, 0, 0)
    assert lump.date == date(2026, 9, 9)
    assert lump.key == lump_key("revolut", "Shared", "roundups", "Travel", "Shared")


def test_pocket_interest_lump_is_keyed_by_both_the_statement_and_the_booked_account() -> None:
    rows = [pocket_income_row(pocket_account="Travel", pocket="Travel", amount="0.01", line=1)]

    (lump,), _, _covered = build_lumps(rows, default_config())

    assert (lump.source_account, lump.account) == ("Shared", "Travel")
    assert lump.key == lump_key("revolut", "Shared", "interest", "Travel", "Travel")


def test_same_named_pockets_of_two_statements_booked_in_one_account_have_different_keys() -> None:
    config = default_config()
    first = [pocket_income_row(pocket_account="Joint pocket", pocket="Home", amount="0.01", line=1)]
    second = [
        pocket_income_row(
            main_account="Other",
            pocket_account="Joint pocket",
            pocket="Home",
            amount="0.01",
            line=1,
        )
    ]

    (lump_a,), _, _ = build_lumps(first, config)
    (lump_b,), _, _ = build_lumps(second, config)

    assert lump_a.account == lump_b.account == "Joint pocket"
    assert lump_a.key != lump_b.key


def test_lump_key_is_eight_hex_chars_and_differs_per_kind_and_pocket() -> None:
    keys = {
        lump_key("revolut", "Main", "roundups", "Travel", "Main"),
        lump_key("revolut", "Main", "roundups", "Food", "Main"),
        lump_key("revolut", "Main", "interest", "Travel", "Main"),
        lump_key("revolut", "Main", "interest", None, "Main"),
    }

    assert len(keys) == 4
    assert all(len(key) == 8 and int(key, 16) >= 0 for key in keys)


# --- Coverage by a previous lump ----------------------------------------------------

SHARED_TRAVEL_KEY = lump_key("revolut", "Shared", "roundups", "Travel", "Shared")


def _group(days: list[int]) -> list[ClassifiedRow]:
    return [roundup(amount="0.10", line=i + 1, day=day) for i, day in enumerate(days)]


def test_no_coverage_gives_the_same_result_as_an_empty_mapping() -> None:
    rows = _group([1, 2, 3])

    assert build_lumps(rows, default_config()) == build_lumps(rows, default_config(), {})
    assert build_lumps(rows, default_config())[2] == ()


def test_cutoff_in_the_middle_of_a_group_splits_it() -> None:
    rows = _group([1, 2, 3, 4])
    covered = {SHARED_TRAVEL_KEY: datetime(2026, 9, 2, 10, 0, 0)}

    lumps, individual, covered_rows = build_lumps(rows, default_config(), covered)

    (lump,) = lumps
    assert [cr.row.line for cr in lump.rows] == [3, 4]
    assert lump.amount == Decimal("0.20")
    assert lump.first == date(2026, 9, 3)
    assert [cr.row.line for cr in covered_rows] == [1, 2]
    assert individual == ()


def test_a_row_exactly_at_the_cutoff_is_covered_and_one_second_later_is_not() -> None:
    rows = _group([5, 5])
    later = ClassifiedRow(
        row=replace(rows[1].row, date=datetime(2026, 9, 5, 10, 0, 1)),
        kind="pocket_move",
        evidence="test",
        counterpart="Travel",
    )
    rows = [rows[0], later]
    covered = {SHARED_TRAVEL_KEY: datetime(2026, 9, 5, 10, 0, 0)}

    lumps, _individual, covered_rows = build_lumps(rows, default_config(), covered)

    assert [cr.row.line for cr in covered_rows] == [1]
    (lump,) = lumps
    assert [cr.row.line for cr in lump.rows] == [2]
    assert lump.cutoff == datetime(2026, 9, 5, 10, 0, 1)


def test_cutoff_has_whole_seconds_so_a_row_with_microseconds_in_that_second_is_covered() -> None:
    rows = _group([5, 5])
    inside = ClassifiedRow(
        row=replace(rows[1].row, date=datetime(2026, 9, 5, 10, 0, 0, 750000)),
        kind="pocket_move",
        evidence="test",
        counterpart="Travel",
    )
    covered = {SHARED_TRAVEL_KEY: datetime(2026, 9, 5, 10, 0, 0)}

    lumps, individual, covered_rows = build_lumps([rows[0], inside], default_config(), covered)

    assert lumps == ()
    assert individual == ()
    assert [cr.row.line for cr in covered_rows] == [1, 2]


def test_a_fully_covered_group_yields_no_lump() -> None:
    rows = _group([1, 2, 3])
    covered = {SHARED_TRAVEL_KEY: datetime(2026, 9, 30, 0, 0, 0)}

    lumps, individual, covered_rows = build_lumps(rows, default_config(), covered)

    assert lumps == ()
    assert individual == ()
    assert covered_rows == tuple(rows)


def test_coverage_of_one_key_does_not_touch_another() -> None:
    rows = [
        roundup(pocket="Travel", amount="0.10", line=1, day=1),
        roundup(pocket="Food", amount="0.10", line=2, day=1),
        savings_row(kind="interest", amount="0.12", line=3, day=1),
    ]
    covered = {SHARED_TRAVEL_KEY: datetime(2026, 9, 30, 0, 0, 0)}

    lumps, individual, covered_rows = build_lumps(rows, default_config(), covered)

    assert [cr.row.line for cr in covered_rows] == [1]
    assert {(lump.kind, lump.pocket) for lump in lumps} == {
        ("roundups", "Food"),
        ("interest", None),
    }
    assert individual == ()


def test_zero_sum_rule_applies_to_what_is_left_after_coverage() -> None:
    rows = [
        roundup(amount="0.30", line=1, day=1),
        roundup(amount="0.10", line=2, day=2),
        roundup(amount="-0.10", line=3, day=3),
    ]
    covered = {SHARED_TRAVEL_KEY: datetime(2026, 9, 1, 23, 0, 0)}

    lumps, individual, covered_rows = build_lumps(rows, default_config(), covered)

    assert lumps == ()
    assert [cr.row.line for cr in covered_rows] == [1]
    assert [cr.row.line for cr in individual] == [2, 3]


def test_pocket_interest_and_savings_rows_are_covered_by_their_own_keys() -> None:
    rows = [
        pocket_income_row(pocket_account="Travel", pocket="Travel", amount="0.01", line=1, day=1),
        pocket_income_row(pocket_account="Travel", pocket="Travel", amount="0.01", line=2, day=9),
        savings_row(kind="fee", amount="-0.01", line=3, day=1),
        savings_row(kind="fee", amount="-0.01", line=4, day=9),
    ]
    covered = {
        lump_key("revolut", "Shared", "interest", "Travel", "Travel"): datetime(2026, 9, 5),
        lump_key("revolut", "Savings", "fee", None, "Savings"): datetime(2026, 9, 5),
    }

    lumps, individual, covered_rows = build_lumps(rows, default_config(), covered)

    assert [cr.row.line for cr in covered_rows] == [1, 3]
    assert {(lump.kind, tuple(cr.row.line for cr in lump.rows)) for lump in lumps} == {
        ("interest", (2,)),
        ("fee", (4,)),
    }
    assert individual == ()


def test_every_input_row_is_in_exactly_one_of_the_three_outputs() -> None:
    purchase = ClassifiedRow(
        row=make_row(amount=Decimal("-3.50"), line=9), kind="purchase", evidence="test"
    )
    rows = [
        *_group([1, 2, 3, 4]),
        roundup(pocket="Food", amount="0.10", line=20, day=1),
        savings_row(kind="interest", amount="0.12", line=21, day=1),
        purchase,
    ]
    covered = {SHARED_TRAVEL_KEY: datetime(2026, 9, 2, 10, 0, 0)}

    lumps, individual, covered_rows = build_lumps(rows, default_config(), covered)

    outputs = [*(cr for lump in lumps for cr in lump.rows), *individual, *covered_rows]
    assert sorted(id(cr) for cr in outputs) == sorted(id(cr) for cr in rows)
