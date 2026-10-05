import tomllib
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.moneywiz.reader import read_snapshot
from smoothment.probe.check import ProbeIncompleteError, check_probe, write_probe_results
from tests.conftest import MakeDb
from tests.moneywiz_fixture import FxAccount, FxCategory, FxTransaction

EUR, EUR2, RUB = 1, 2, 3
ACCOUNTS = [
    FxAccount(EUR, "SMT Probe EUR"),
    FxAccount(EUR2, "SMT Probe EUR 2"),
    FxAccount(RUB, "SMT Probe RUB", "RUB"),
]
CATS = [FxCategory(10, "Groceries")]


def _best_case() -> list[FxTransaction]:
    return [
        FxTransaction(
            100, 48, EUR, -12.34, datetime(2026, 1, 5), notes="smt:probe:plain", categories=(10,)
        ),
        FxTransaction(
            101,
            47,
            EUR,
            -20.0,
            datetime(2026, 1, 6),
            notes="smt:probe:single",
            recipient_account=EUR2,
        ),
        FxTransaction(102, 46, EUR2, 20.0, datetime(2026, 1, 6), sender_account=EUR),
        FxTransaction(
            103,
            47,
            EUR,
            -30.0,
            datetime(2026, 1, 7),
            notes="smt:probe:two-out",
            recipient_account=EUR2,
        ),
        FxTransaction(
            104, 46, EUR2, 30.0, datetime(2026, 1, 7), notes="smt:probe:two-in", sender_account=EUR
        ),
        FxTransaction(
            105, 47, EUR, -40.0, datetime(2026, 1, 8), notes="smt:probe:xcur", recipient_account=RUB
        ),
        FxTransaction(106, 46, RUB, 3600.0, datetime(2026, 1, 8), sender_account=EUR),
        FxTransaction(
            107,
            47,
            EUR,
            -33.0,
            datetime(2026, 1, 9),
            notes="smt:probe:existing",
            recipient_account=EUR2,
        ),
        FxTransaction(108, 46, EUR2, 33.0, datetime(2026, 1, 9), sender_account=EUR),
    ]


def test_best_case_all_true(moneywiz_db: MakeDb) -> None:
    result = check_probe(read_snapshot(moneywiz_db(ACCOUNTS, CATS, [], _best_case())))
    assert result.memo_lands_in_notes is True
    assert result.single_leg_creates_reciprocal is True
    assert result.two_legs_link_once is True
    assert result.existing_leg_links is True
    assert result.cross_currency_reciprocal_amount == Decimal("3600.00")


def test_worst_case_all_false(moneywiz_db: MakeDb) -> None:
    rows = [
        FxTransaction(100, 48, EUR, -12.34, datetime(2026, 1, 5), notes=""),
        FxTransaction(101, 48, EUR, -20.0, datetime(2026, 1, 6)),
        FxTransaction(103, 47, EUR, -30.0, datetime(2026, 1, 7), recipient_account=EUR2),
        FxTransaction(104, 46, EUR2, 30.0, datetime(2026, 1, 7), sender_account=EUR),
        FxTransaction(109, 47, EUR, -30.0, datetime(2026, 1, 7), recipient_account=EUR2),
        FxTransaction(110, 46, EUR2, 30.0, datetime(2026, 1, 7), sender_account=EUR),
        FxTransaction(105, 48, EUR, -40.0, datetime(2026, 1, 8)),
        FxTransaction(107, 47, EUR, -33.0, datetime(2026, 1, 9), recipient_account=EUR2),
        FxTransaction(108, 38, EUR2, 33.0, datetime(2026, 1, 9)),
        FxTransaction(111, 46, EUR2, 33.0, datetime(2026, 1, 9), sender_account=EUR),
    ]
    result = check_probe(read_snapshot(moneywiz_db(ACCOUNTS, CATS, [], rows)))
    assert result.memo_lands_in_notes is False
    assert result.single_leg_creates_reciprocal is False
    assert result.two_legs_link_once is False
    assert result.existing_leg_links is False
    assert result.cross_currency_reciprocal_amount is None
    assert any("duplicate" in n.lower() for n in result.notes)


def test_missing_probe_accounts_raise(moneywiz_db: MakeDb) -> None:
    with pytest.raises(ProbeIncompleteError) as exc:
        check_probe(read_snapshot(moneywiz_db([FxAccount(1, "Revolut")], [], [], [])))
    assert "SMT Probe EUR" in str(exc.value)


def test_missing_plain_row_raises(moneywiz_db: MakeDb) -> None:
    with pytest.raises(ProbeIncompleteError):
        check_probe(read_snapshot(moneywiz_db(ACCOUNTS, CATS, [], [])))


def test_write_probe_results_creates_overlay(moneywiz_db: MakeDb, tmp_path: Path) -> None:
    result = check_probe(read_snapshot(moneywiz_db(ACCOUNTS, CATS, [], _best_case())))
    out = write_probe_results(result, tmp_path / "smoothment.toml")
    assert out == tmp_path / "smoothment.probe.toml"
    data = tomllib.loads(out.read_text())
    assert data["moneywiz"] == {
        "memo_lands_in_notes": True,
        "single_leg_creates_reciprocal": True,
        "two_legs_link_once": True,
        "existing_leg_links": True,
    }
