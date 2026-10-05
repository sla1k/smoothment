import random
from datetime import datetime
from decimal import Decimal
from itertools import permutations
from typing import Any

from smoothment.classify import classify_row
from smoothment.classify.model import ClassifiedRow, RowKind
from smoothment.config import AccountEntry, TransferSettings
from smoothment.link import LinkResult, Transfer, link
from tests.classify_fixtures import make_config, make_context, make_row

SETTINGS = TransferSettings()


_ROW_FIELDS = {
    "bank",
    "account",
    "line",
    "date",
    "has_time",
    "amount",
    "currency",
    "description",
}


def cr(*, kind: RowKind = "own_transfer", **overrides: Any) -> ClassifiedRow:
    row_overrides = {key: value for key, value in overrides.items() if key in _ROW_FIELDS}
    classified_overrides = {
        key: value for key, value in overrides.items() if key not in _ROW_FIELDS
    }
    row = make_row(**row_overrides)
    return ClassifiedRow(row=row, kind=kind, evidence="test", **classified_overrides)


def single_transfer(result: LinkResult) -> Transfer:
    assert len(result.transfers) == 1
    return result.transfers[0]


# --- plain pairing -----------------------------------------------------------


def test_plain_pair_across_two_accounts() -> None:
    out = cr(account="Black", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 10, 0, 0))
    inc = cr(account="Safety", amount=Decimal("100.00"), date=datetime(2026, 9, 1, 10, 5, 0))
    result = link([out, inc], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is out
    assert transfer.incoming is inc
    assert transfer.source == "Black"
    assert transfer.destination == "Safety"
    assert transfer.note == "paired 00:05:00 apart"
    assert result.unmatched == ()


def test_amount_within_tolerance_pairs() -> None:
    # 2% of 100.00 is 2.00; 1.99 gap is within tolerance.
    out = cr(account="Black", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 10, 0, 0))
    inc = cr(account="Safety", amount=Decimal("101.99"), date=datetime(2026, 9, 1, 10, 5, 0))
    result = link([out, inc], SETTINGS)
    assert len(result.transfers) == 1
    assert result.unmatched == ()


def test_amount_beyond_tolerance_does_not_pair() -> None:
    # 2% of 105.00 is 2.10; a 5.00 gap is well beyond that.
    out = cr(account="Black", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 10, 0, 0))
    inc = cr(account="Safety", amount=Decimal("105.00"), date=datetime(2026, 9, 1, 10, 5, 0))
    result = link([out, inc], SETTINGS)
    assert result.transfers == ()
    assert set(result.unmatched) == {out, inc}


def test_amount_gap_exactly_at_tolerance_pairs() -> None:
    # 2% of the larger amount (100.00) is exactly 2.00, matching the gap exactly (<=).
    out = cr(account="Black", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 10, 0, 0))
    inc = cr(account="Safety", amount=Decimal("98.00"), date=datetime(2026, 9, 1, 10, 5, 0))
    result = link([out, inc], SETTINGS)
    assert len(result.transfers) == 1


def test_three_days_apart_pairs() -> None:
    out = cr(account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 1, 9, 0, 0))
    inc = cr(account="Safety", amount=Decimal("50.00"), date=datetime(2026, 9, 4, 9, 0, 0))
    result = link([out, inc], SETTINGS)
    assert len(result.transfers) == 1


def test_four_days_apart_does_not_pair() -> None:
    out = cr(account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 1, 9, 0, 0))
    inc = cr(account="Safety", amount=Decimal("50.00"), date=datetime(2026, 9, 5, 9, 0, 0))
    result = link([out, inc], SETTINGS)
    assert result.transfers == ()
    assert set(result.unmatched) == {out, inc}


def test_same_account_never_pairs() -> None:
    out = cr(account="Black", amount=Decimal("-50.00"), date=datetime(2026, 9, 1, 9, 0, 0))
    inc = cr(account="Black", amount=Decimal("50.00"), date=datetime(2026, 9, 1, 9, 5, 0))
    result = link([out, inc], SETTINGS)
    assert result.transfers == ()
    assert set(result.unmatched) == {out, inc}


# --- allowed -------------------------------------------------------------------


def test_allowed_rejects_wrong_account() -> None:
    # `out.allowed` excludes "Other", so the pair is infeasible; since `allowed` has exactly
    # one account and no partner was found, `out` falls back to a single leg into it.
    out = cr(
        account="Black",
        amount=Decimal("-50.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Safety"}),
    )
    inc = cr(account="Other", amount=Decimal("50.00"), date=datetime(2026, 9, 1, 9, 5, 0))
    result = link([out, inc], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is out
    assert transfer.destination == "Safety"
    assert transfer.note == "single leg: only possible counterpart"
    assert result.unmatched == (inc,)


def test_allowed_accepts_right_account() -> None:
    out = cr(
        account="Black",
        amount=Decimal("-50.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Safety"}),
    )
    inc = cr(account="Safety", amount=Decimal("50.00"), date=datetime(2026, 9, 1, 9, 5, 0))
    result = link([out, inc], SETTINGS)
    assert len(result.transfers) == 1


# --- currency --------------------------------------------------------------------


def test_cross_currency_pair_ignores_amount_tolerance() -> None:
    out = cr(
        account="Black",
        amount=Decimal("-100.00"),
        currency="EUR",
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Safety"}),
    )
    inc = cr(
        account="Safety",
        amount=Decimal("87.15"),
        currency="GBP",
        date=datetime(2026, 9, 1, 9, 5, 0),
        allowed=frozenset({"Black", "Other"}),
    )
    result = link([out, inc], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is out
    assert transfer.incoming is inc
    assert (transfer.source, transfer.destination) == ("Black", "Safety")
    assert transfer.note == "paired 00:05:00 apart, 100.00 EUR against 87.15 GBP"
    assert result.unmatched == ()


def test_cross_currency_pair_with_evidence_on_both_legs_names_both_amounts() -> None:
    out = cr(
        account="Revolut",
        amount=Decimal("-50.00"),
        currency="EUR",
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Black"}),
    )
    inc = cr(
        account="Black",
        amount=Decimal("32500"),
        currency="RUB",
        date=datetime(2026, 9, 2, 1, 30, 0),
        allowed=frozenset({"Revolut", "Wise"}),
    )
    transfer = single_transfer(link([out, inc], SETTINGS))
    assert transfer.outgoing is out
    assert transfer.incoming is inc
    assert transfer.note == "paired 16:30:00 apart, 50.00 EUR against 32500 RUB"


def test_cross_currency_candidates_without_evidence_do_not_pair() -> None:
    out = cr(
        account="Revolut",
        amount=Decimal("-50.00"),
        currency="EUR",
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=None,
    )
    inc = cr(
        account="Black",
        amount=Decimal("32500"),
        currency="RUB",
        date=datetime(2026, 9, 3, 1, 30, 0),
        allowed=None,
    )
    result = link([out, inc], SETTINGS)
    assert result.transfers == ()
    assert set(result.unmatched) == {out, inc}


def test_cross_currency_needs_evidence_on_both_legs() -> None:
    out = cr(
        account="Revolut",
        amount=Decimal("-50.00"),
        currency="EUR",
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Black", "Wise"}),
    )
    inc = cr(
        account="Black",
        amount=Decimal("32500"),
        currency="RUB",
        date=datetime(2026, 9, 1, 10, 0, 0),
        allowed=None,
    )
    result = link([out, inc], SETTINGS)
    assert result.transfers == ()
    assert set(result.unmatched) == {out, inc}


def test_cross_currency_candidate_does_not_take_the_same_currency_leg() -> None:
    out = cr(
        account="Revolut",
        amount=Decimal("-44.00"),
        currency="EUR",
        date=datetime(2026, 9, 1, 17, 0, 0),
        allowed=None,
    )
    wise = cr(
        account="Wise",
        amount=Decimal("44.00"),
        currency="EUR",
        date=datetime(2026, 9, 1, 18, 4, 0),
        allowed=None,
    )
    rub = cr(
        account="Sovcombank",
        amount=Decimal("32500"),
        currency="RUB",
        date=datetime(2026, 9, 1, 17, 30, 0),
        allowed=None,
    )
    for order in permutations([out, wise, rub]):
        result = link(list(order), SETTINGS)
        transfer = single_transfer(result)
        assert transfer.outgoing is out
        assert transfer.incoming is wise
        assert result.unmatched == (rub,)


def test_same_currency_pair_ranks_before_a_closer_cross_currency_pair() -> None:
    out = cr(
        account="Revolut",
        amount=Decimal("-44.00"),
        currency="EUR",
        date=datetime(2026, 9, 1, 17, 0, 0),
        allowed=frozenset({"Black", "Wise"}),
    )
    wise = cr(
        account="Wise",
        amount=Decimal("44.00"),
        currency="EUR",
        date=datetime(2026, 9, 2, 18, 4, 0),
        allowed=None,
    )
    rub = cr(
        account="Black",
        amount=Decimal("3000"),
        currency="RUB",
        date=datetime(2026, 9, 1, 17, 1, 0),
        allowed=frozenset({"Revolut", "Platinum"}),
    )
    for order in permutations([out, wise, rub]):
        result = link(list(order), SETTINGS)
        transfer = single_transfer(result)
        assert transfer.outgoing is out
        assert transfer.incoming is wise
        assert result.unmatched == (rub,)
        assert result.notes == ()


def test_unequal_same_currency_pair_names_both_amounts_and_the_difference() -> None:
    out = cr(account="Revolut", amount=Decimal("-101.50"), date=datetime(2026, 9, 1, 10, 0, 0))
    inc = cr(account="Shared", amount=Decimal("100.00"), date=datetime(2026, 9, 1, 10, 0, 1))
    transfer = single_transfer(link([out, inc], SETTINGS))
    assert transfer.outgoing is out
    assert transfer.incoming is inc
    assert transfer.note == "paired 00:00:01 apart, 101.50 against 100.00 (difference 1.50)"


# --- competing legs / ties ---------------------------------------------------


def test_closer_timestamp_wins_the_other_is_unmatched() -> None:
    inc = cr(account="Safety", amount=Decimal("100.00"), date=datetime(2026, 9, 1, 10, 0, 0))
    close = cr(account="Black", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 9, 55, 0))
    far = cr(account="Other", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 8, 0, 0))
    result = link([inc, close, far], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is close
    assert transfer.incoming is inc
    assert result.unmatched == (far,)


def test_closer_timestamp_wins_the_other_becomes_single_leg() -> None:
    # `far` is a genuine competitor for `inc` (its `allowed` permits "Safety"); it just loses
    # the race to `close`. Losing, it still has exactly one allowed account, so it falls back
    # to a single leg into that same account rather than going unmatched.
    inc = cr(account="Safety", amount=Decimal("100.00"), date=datetime(2026, 9, 1, 10, 0, 0))
    close = cr(account="Black", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 9, 55, 0))
    far = cr(
        account="Other",
        amount=Decimal("-100.00"),
        date=datetime(2026, 9, 1, 8, 0, 0),
        allowed=frozenset({"Safety"}),
    )
    result = link([inc, close, far], SETTINGS)
    assert len(result.transfers) == 2
    single = next(t for t in result.transfers if t.outgoing is far)
    assert single.incoming is None
    assert single.source == "Other"
    assert single.destination == "Safety"
    assert single.note == "single leg: only possible counterpart"
    assert "counterpart not found in Safety for Other 2026-09-01T08:00:00 -100.00" in result.notes
    assert result.unmatched == ()


def test_tie_produces_note_and_stable_across_permutations() -> None:
    inc = cr(account="Safety", amount=Decimal("100.00"), date=datetime(2026, 9, 1, 10, 0, 0))
    a = cr(account="Black", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 9, 55, 0))
    b = cr(account="Other", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 10, 5, 0))

    results = [link(list(order), SETTINGS) for order in permutations([inc, a, b])]
    first = results[0]
    assert len(first.notes) == 1
    assert len(first.transfers) == 1
    assert first.transfers[0].outgoing in (a, b)
    assert len(first.unmatched) == 1
    for result in results[1:]:
        assert result == first


def test_single_leg_and_unmatched_stable_across_permutations() -> None:
    single = cr(
        account="Black",
        amount=Decimal("-50.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Savings"}),
    )
    unmatched_row = cr(
        account="Other",
        amount=Decimal("-30.00"),
        date=datetime(2026, 9, 3, 9, 0, 0),
        allowed=None,
    )
    results = [link(list(order), SETTINGS) for order in permutations([single, unmatched_row])]
    first = results[0]
    assert len(first.transfers) == 1
    assert first.transfers[0].outgoing is single
    assert first.unmatched == (unmatched_row,)
    for result in results[1:]:
        assert result == first


# --- date-only vs timed legs --------------------------------------------------


def test_date_only_leg_against_timed_leg_uses_whole_days() -> None:
    out = cr(
        account="Black",
        amount=Decimal("-50.00"),
        date=datetime(2026, 9, 1, 23, 55, 0),
        has_time=True,
    )
    inc = cr(
        account="Safety",
        amount=Decimal("50.00"),
        date=datetime(2026, 9, 2, 0, 0, 0),
        has_time=False,
    )
    result = link([out, inc], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.note == "paired 1 day apart"


def test_date_only_leg_on_next_calendar_day_pairs_with_one_day_gap() -> None:
    out = cr(
        account="Black",
        amount=Decimal("-50.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        has_time=True,
    )
    inc = cr(
        account="Safety",
        amount=Decimal("50.00"),
        date=datetime(2026, 9, 2, 0, 0, 0),
        has_time=False,
    )
    result = link([out, inc], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.note == "paired 1 day apart"


def _pair_key(transfer: Transfer) -> tuple[str, str]:
    return (transfer.source, transfer.destination)


def _alpha_beta_gamma_rows(
    middle: str = "Beta",
) -> tuple[ClassifiedRow, ClassifiedRow, ClassifiedRow, ClassifiedRow]:
    amount = Decimal("500.00")
    alpha_out = cr(
        account="Alpha",
        line=1,
        amount=-amount,
        date=datetime(2026, 7, 20),
        has_time=False,
    )
    beta_in = cr(
        account=middle,
        line=1,
        amount=amount,
        date=datetime(2026, 7, 20, 4, 34, 54),
    )
    beta_out = cr(
        account=middle,
        line=2,
        amount=-amount,
        date=datetime(2026, 7, 20, 4, 35, 43),
    )
    gamma_in = cr(
        account="Gamma",
        line=1,
        amount=amount,
        date=datetime(2026, 7, 20, 4, 35, 43),
    )
    return alpha_out, beta_in, beta_out, gamma_in


def test_timed_zero_gap_pair_outranks_same_day_date_only_pair_across_permutations() -> None:
    for middle in ("Beta", "Zeta"):
        alpha_out, beta_in, beta_out, gamma_in = _alpha_beta_gamma_rows(middle)
        for order in permutations([alpha_out, beta_in, beta_out, gamma_in]):
            result = link(list(order), SETTINGS)
            assert [_pair_key(t) for t in result.transfers] == [
                ("Alpha", middle),
                (middle, "Gamma"),
            ]
            by_source = {t.source: t for t in result.transfers}
            assert by_source["Alpha"].outgoing is alpha_out
            assert by_source["Alpha"].incoming is beta_in
            assert by_source["Alpha"].note == "paired 0 days apart"
            assert by_source[middle].outgoing is beta_out
            assert by_source[middle].incoming is gamma_in
            assert by_source[middle].note == "paired 00:00:00 apart"
            assert result.unmatched == ()


def test_bounced_transfer_leaves_extra_date_only_rows_unmatched_across_permutations() -> None:
    for middle in ("Beta", "Zeta"):
        alpha_out, beta_in, beta_out, gamma_in = _alpha_beta_gamma_rows(middle)
        extra_out = cr(
            account="Alpha",
            line=2,
            amount=Decimal("-500.00"),
            date=datetime(2026, 7, 20),
            has_time=False,
        )
        extra_in = cr(
            account="Alpha",
            line=3,
            amount=Decimal("500.00"),
            date=datetime(2026, 7, 22),
            has_time=False,
        )
        rows = [alpha_out, beta_in, beta_out, gamma_in, extra_out, extra_in]
        for order in permutations(rows):
            result = link(list(order), SETTINGS)
            assert [_pair_key(t) for t in result.transfers] == [
                ("Alpha", middle),
                (middle, "Gamma"),
            ]
            by_source = {t.source: t for t in result.transfers}
            assert by_source["Alpha"].outgoing is alpha_out
            assert by_source["Alpha"].incoming is beta_in
            assert by_source[middle].outgoing is beta_out
            assert by_source[middle].incoming is gamma_in
            assert set(result.unmatched) == {extra_out, extra_in}


def test_timed_pair_thirteen_hours_apart_loses_to_same_day_date_only_pair() -> None:
    inc = cr(account="Safety", amount=Decimal("100.00"), date=datetime(2026, 9, 1, 13, 30, 0))
    timed = cr(account="Black", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 0, 30, 0))
    date_only = cr(
        account="Other",
        amount=Decimal("-100.00"),
        date=datetime(2026, 9, 1),
        has_time=False,
    )
    result = link([inc, timed, date_only], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is date_only
    assert transfer.note == "paired 0 days apart"
    assert result.unmatched == (timed,)


def test_timed_pair_eleven_hours_apart_beats_same_day_date_only_pair() -> None:
    inc = cr(account="Safety", amount=Decimal("100.00"), date=datetime(2026, 9, 1, 11, 30, 0))
    timed = cr(account="Black", amount=Decimal("-100.00"), date=datetime(2026, 9, 1, 0, 30, 0))
    date_only = cr(
        account="Other",
        amount=Decimal("-100.00"),
        date=datetime(2026, 9, 1),
        has_time=False,
    )
    result = link([inc, timed, date_only], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is timed
    assert transfer.note == "paired 11:00:00 apart"
    assert result.unmatched == (date_only,)


def test_date_only_pair_one_day_apart_loses_to_same_day_date_only_pair() -> None:
    inc = cr(account="Safety", amount=Decimal("100.00"), date=datetime(2026, 9, 2), has_time=False)
    same_day = cr(
        account="Other",
        amount=Decimal("-100.00"),
        date=datetime(2026, 9, 2),
        has_time=False,
    )
    day_before = cr(
        account="Black",
        amount=Decimal("-100.00"),
        date=datetime(2026, 9, 1),
        has_time=False,
    )
    result = link([inc, day_before, same_day], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is same_day
    assert transfer.note == "paired 0 days apart"
    assert result.unmatched == (day_before,)


# --- single leg / unmatched ---------------------------------------------------


def test_single_leg_from_one_element_allowed() -> None:
    row = cr(
        account="Black",
        amount=Decimal("-50.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Savings"}),
    )
    result = link([row], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is row
    assert transfer.incoming is None
    assert transfer.source == "Black"
    assert transfer.destination == "Savings"
    assert transfer.note == "single leg: only possible counterpart"
    assert result.notes == (
        "counterpart not found in Savings for Black 2026-09-01T09:00:00 -50.00",
    )
    assert result.unmatched == ()


def test_single_leg_from_one_element_allowed_positive_row() -> None:
    row = cr(
        account="Black",
        amount=Decimal("50.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Savings"}),
    )
    result = link([row], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is None
    assert transfer.incoming is row
    assert transfer.source == "Savings"
    assert transfer.destination == "Black"


def test_empty_allowed_set_is_unmatched() -> None:
    row = cr(
        account="Black",
        amount=Decimal("-50.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset(),
    )
    result = link([row], SETTINGS)
    assert result.transfers == ()
    assert result.unmatched == (row,)


def test_allowed_with_multiple_accounts_and_no_partner_is_unmatched() -> None:
    row = cr(
        account="Black",
        amount=Decimal("-50.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Savings", "Wallet"}),
    )
    result = link([row], SETTINGS)
    assert result.transfers == ()
    assert result.unmatched == (row,)


def test_allowed_none_with_no_partner_is_unmatched() -> None:
    row = cr(
        account="Black",
        amount=Decimal("-50.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=None,
    )
    result = link([row], SETTINGS)
    assert result.transfers == ()
    assert result.unmatched == (row,)


def test_pair_only_row_with_one_allowed_account_and_no_partner_is_unmatched() -> None:
    row = cr(
        account="BBVA",
        amount=Decimal("100.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Revolut"}),
        pair_only=True,
    )
    result = link([row], SETTINGS)
    assert result.transfers == ()
    assert result.unmatched == (row,)
    assert result.notes == ()


def _bbva_marker_row() -> ClassifiedRow:
    config = make_config(
        accounts=[
            AccountEntry(bank="revolut", moneywiz="Revolut", acct_id="1"),
            AccountEntry(bank="bbva", moneywiz="BBVA", acct_id="2"),
        ]
    )
    row = make_row(
        bank="bbva",
        account="BBVA",
        description="Transfer received",
        bank_type="Sent from revolut",
        amount=Decimal("100.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
    )
    return classify_row(row, make_context(config))


def test_bbva_marker_row_without_partner_is_unmatched_not_a_transfer() -> None:
    marker = _bbva_marker_row()
    assert marker.allowed == frozenset({"Revolut"})
    result = link([marker], SETTINGS)
    assert result.transfers == ()
    assert result.unmatched == (marker,)


def test_bbva_marker_row_with_partner_pairs() -> None:
    marker = _bbva_marker_row()
    partner = cr(
        account="Revolut",
        amount=Decimal("-100.00"),
        date=datetime(2026, 9, 1, 8, 59, 0),
        allowed=None,
    )
    transfer = single_transfer(link([marker, partner], SETTINGS))
    assert transfer.outgoing is partner
    assert transfer.incoming is marker
    assert (transfer.source, transfer.destination) == ("Revolut", "BBVA")


def test_santander_owner_row_with_revolut_reference_and_no_partner_is_a_single_leg() -> None:
    config = make_config(
        accounts=[
            AccountEntry(bank="revolut", moneywiz="Revolut", acct_id="1"),
            AccountEntry(bank="santander", moneywiz="Santander", acct_id="2"),
        ]
    )
    row = make_row(
        bank="santander",
        account="Santander",
        description="Transferencia De Sample Owner",
        bank_type="Transferencia",
        counterparty="Sample Owner",
        reference="Sent From Revolut",
        amount=Decimal("100.00"),
        date=datetime(2026, 9, 1),
        has_time=False,
    )
    named = classify_row(row, make_context(config))
    assert named.allowed == frozenset({"Revolut"})
    result = link([named], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.incoming is named
    assert (transfer.source, transfer.destination) == ("Revolut", "Santander")
    assert transfer.note == "single leg: only possible counterpart"
    assert result.unmatched == ()


# --- pocket move and cash -----------------------------------------------------


def test_pocket_move_negative_becomes_transfer_out_of_account() -> None:
    row = cr(
        kind="pocket_move",
        account="Black",
        amount=Decimal("-5.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        counterpart="Pocket: Holiday",
    )
    result = link([row], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is row
    assert transfer.incoming is None
    assert transfer.source == "Black"
    assert transfer.destination == "Pocket: Holiday"
    assert transfer.note == "pocket move"


def test_pocket_move_positive_becomes_transfer_into_account() -> None:
    row = cr(
        kind="pocket_move",
        account="Black",
        amount=Decimal("5.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        counterpart="Pocket: Holiday",
    )
    result = link([row], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is None
    assert transfer.incoming is row
    assert transfer.source == "Pocket: Holiday"
    assert transfer.destination == "Black"
    assert transfer.note == "pocket move"


def test_cash_negative_becomes_transfer_out_of_account() -> None:
    row = cr(
        kind="cash",
        account="Black",
        amount=Decimal("-20.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        counterpart="Cash",
    )
    result = link([row], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is row
    assert transfer.incoming is None
    assert transfer.source == "Black"
    assert transfer.destination == "Cash"
    assert transfer.note == "cash"


def test_cash_positive_becomes_transfer_into_account() -> None:
    row = cr(
        kind="cash",
        account="Black",
        amount=Decimal("20.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        counterpart="Cash",
    )
    result = link([row], SETTINGS)
    transfer = single_transfer(result)
    assert transfer.outgoing is None
    assert transfer.incoming is row
    assert transfer.source == "Cash"
    assert transfer.destination == "Black"
    assert transfer.note == "cash"


# --- other kinds ---------------------------------------------------------------


def test_other_kinds_never_appear_in_result() -> None:
    kinds: list[RowKind] = [
        "pocket_income",
        "third_party",
        "purchase",
        "refund",
        "fee",
        "interest",
        "cashback",
        "income",
        "excluded",
    ]
    rows = [
        cr(kind=kind, account="Black", amount=Decimal("-10.00" if i % 2 else "10.00"))
        for i, kind in enumerate(kinds)
    ]
    result = link(rows, SETTINGS)
    assert result.transfers == ()
    assert result.unmatched == ()
    assert result.notes == ()


# --- regression cases: amount+date alone must never pair ---------------------


def test_regression_third_party_payment_into_joint_and_own_withdrawal_do_not_pair() -> None:
    third_party = cr(
        kind="third_party",
        account="Joint",
        amount=Decimal("100.00"),
        date=datetime(2026, 7, 3, 10, 0, 0),
    )
    own_withdrawal = cr(
        kind="own_transfer",
        account="Black",
        amount=Decimal("-100.00"),
        date=datetime(2026, 7, 3, 11, 0, 0),
        allowed=None,
    )
    result = link([third_party, own_withdrawal], SETTINGS)
    assert result.transfers == ()
    assert result.unmatched == (own_withdrawal,)


def test_regression_payment_to_friend_and_incoming_own_transfer_do_not_pair() -> None:
    payment_to_friend = cr(
        kind="third_party",
        account="Black",
        amount=Decimal("-40.00"),
        date=datetime(2026, 7, 5, 10, 0, 0),
    )
    incoming_own = cr(
        kind="own_transfer",
        account="Safety",
        amount=Decimal("40.00"),
        date=datetime(2026, 7, 5, 10, 5, 0),
        allowed=None,
    )
    result = link([payment_to_friend, incoming_own], SETTINGS)
    assert result.transfers == ()
    assert result.unmatched == (incoming_own,)


def test_regression_pocket_move_and_unrelated_own_transfer_do_not_pair() -> None:
    pocket = cr(
        kind="pocket_move",
        account="Black",
        amount=Decimal("-15.00"),
        date=datetime(2026, 7, 10, 10, 0, 0),
        counterpart="Pocket: Savings",
    )
    unrelated = cr(
        kind="own_transfer",
        account="Safety",
        amount=Decimal("15.00"),
        date=datetime(2026, 7, 10, 10, 5, 0),
        allowed=None,
    )
    result = link([pocket, unrelated], SETTINGS)
    pocket_transfer = single_transfer(result)
    assert pocket_transfer.outgoing is pocket
    assert pocket_transfer.note == "pocket move"
    assert result.unmatched == (unrelated,)


# --- deterministic ordering ----------------------------------------------------


def test_transfers_ordered_by_date_of_first_leg_then_account() -> None:
    later = cr(
        account="Black",
        amount=Decimal("-10.00"),
        date=datetime(2026, 9, 5, 9, 0, 0),
        allowed=frozenset({"Vault"}),
    )
    earlier = cr(
        account="Alpha",
        amount=Decimal("-10.00"),
        date=datetime(2026, 9, 1, 9, 0, 0),
        allowed=frozenset({"Vault"}),
    )
    result = link([later, earlier], SETTINGS)
    assert [t.outgoing for t in result.transfers] == [earlier, later]


def test_transfers_ordering_is_stable_under_shuffling_with_shared_dates_and_accounts() -> None:
    # Several single-leg fallbacks, pocket moves and cash rows all share one (date, account),
    # so they tie on the transfer-ordering key's first two components; only the full
    # content-based key can tell them apart. Each single-leg candidate's `allowed` names an
    # account no other row uses, so it can only ever resolve as a single leg, never pair.
    shared_date = datetime(2026, 9, 5, 9, 0, 0)
    shared_account = "Black"
    single_legs = [
        cr(
            account=shared_account,
            amount=amount,
            date=shared_date,
            line=100 + i,
            description=f"single leg {i}",
            allowed=frozenset({f"Only{i}"}),
        )
        for i, amount in enumerate(
            [Decimal("-10.00"), Decimal("-11.00"), Decimal("12.00"), Decimal("-13.00")]
        )
    ]
    pocket_and_cash_specs: list[tuple[RowKind, Decimal, str]] = [
        ("pocket_move", Decimal("-5.00"), "Pocket A"),
        ("pocket_move", Decimal("6.00"), "Pocket B"),
        ("cash", Decimal("-7.00"), "Cash"),
        ("cash", Decimal("8.00"), "Cash"),
        ("cash", Decimal("9.00"), "Cash"),
    ]
    pocket_and_cash = [
        cr(
            kind=kind,
            account=shared_account,
            amount=amount,
            date=shared_date,
            line=200 + i,
            description=f"{kind} {i}",
            counterpart=counterpart,
        )
        for i, (kind, amount, counterpart) in enumerate(pocket_and_cash_specs)
    ]

    pair1_out = cr(account="P1A", amount=Decimal("-20.00"), date=datetime(2026, 9, 1, 10, 0, 0))
    pair1_in = cr(account="P1B", amount=Decimal("20.00"), date=datetime(2026, 9, 1, 10, 5, 0))
    pair2_out = cr(account="P2A", amount=Decimal("-30.00"), date=datetime(2026, 9, 2, 11, 0, 0))
    pair2_in = cr(account="P2B", amount=Decimal("30.00"), date=datetime(2026, 9, 2, 11, 3, 0))

    unmatched_none = cr(
        account="U1", amount=Decimal("-40.00"), date=datetime(2026, 9, 3, 9, 0, 0), allowed=None
    )
    unmatched_multi = cr(
        account="U2",
        amount=Decimal("41.00"),
        date=datetime(2026, 9, 3, 10, 0, 0),
        allowed=frozenset({"A", "B"}),
    )

    rows = [
        *single_legs,
        *pocket_and_cash,
        pair1_out,
        pair1_in,
        pair2_out,
        pair2_in,
        unmatched_none,
        unmatched_multi,
    ]
    assert len(rows) == 15

    baseline = link(rows, SETTINGS)
    assert len(baseline.transfers) == 4 + 5 + 2  # single legs + pocket/cash + 2 real pairs
    assert len(baseline.unmatched) == 2

    rng = random.Random(20260928)
    for _ in range(200):
        shuffled = list(rows)
        rng.shuffle(shuffled)
        assert link(shuffled, SETTINGS) == baseline
