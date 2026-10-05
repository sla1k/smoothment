import csv
from decimal import Decimal
from pathlib import Path

from smoothment.probe.fixture import (
    PROBE_ACCOUNT_EUR,
    PROBE_ACCOUNT_EUR_2,
    PROBE_ACCOUNT_RUB,
    probe_instructions,
    probe_rows,
    write_probe_csv,
)


def test_probe_rows_cover_all_cases() -> None:
    rows = probe_rows("Food & Dining > Groceries")
    memos = [r.memo for r in rows]
    assert memos == [
        "smt:probe:plain",
        "smt:probe:single",
        "smt:probe:two-out",
        "smt:probe:two-in",
        "smt:probe:xcur",
        "smt:probe:existing",
    ]
    assert rows[0].category == "Food & Dining > Groceries" and rows[0].transfers == ""
    assert rows[1].transfers == PROBE_ACCOUNT_EUR_2
    assert rows[2].amount == Decimal("-30.00") and rows[3].amount == Decimal("30.00")
    assert rows[3].account == PROBE_ACCOUNT_EUR_2 and rows[3].transfers == PROBE_ACCOUNT_EUR
    assert rows[4].transfers == PROBE_ACCOUNT_RUB
    assert all(r.category == "" for r in rows[1:])


def test_write_probe_csv_format(tmp_path: Path) -> None:
    out = tmp_path / "probe.csv"
    write_probe_csv(out, "Food & Dining > Groceries")
    text = out.read_text(encoding="utf-8")
    assert (
        text.splitlines()[0]
        == '"Date","Amount","Payee","Description","Category","Account","Transfers","Memo"'
    )
    expected_row = (
        '"2026-01-05","-12.34","SMT Probe Shop","probe plain",'
        '"Food & Dining > Groceries","SMT Probe EUR","","smt:probe:plain"'
    )
    assert expected_row in text
    assert "\r" not in text
    with out.open(newline="", encoding="utf-8") as fh:
        parsed = list(csv.DictReader(fh))
    assert len(parsed) == 6
    assert parsed[4]["Transfers"] == PROBE_ACCOUNT_RUB


def test_instructions_mention_manual_steps(tmp_path: Path) -> None:
    text = probe_instructions(tmp_path / "probe.csv", "Food & Dining > Groceries")
    for needle in (
        PROBE_ACCOUNT_EUR,
        PROBE_ACCOUNT_EUR_2,
        PROBE_ACCOUNT_RUB,
        "33.00",
        "2026-01-09",
        "probe check",
    ):
        assert needle in text
