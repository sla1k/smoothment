import csv
import shutil
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from smoothment.classify.model import ClassifiedRow
from smoothment.config import Config, ConfigError
from smoothment.convert import ConvertResult, FileResult, run_convert
from smoothment.export import COLUMNS
from smoothment.statement.model import ParsedStatement, StatementRow
from smoothment.statement.parsers import PARSERS
from tests.conftest import (
    FIXTURES,
    ROUNDUPS_CONFIG,
    ROUNDUPS_CSV,
    STATEMENT_CONFIG,
    inflate_wise_input_rows,
)
from tests.snapshot_fixtures import exported_names, snapshot_of


def _row() -> StatementRow:
    return StatementRow(
        bank="revolut",
        account="Main",
        line=1,
        date=datetime(2026, 1, 1),
        has_time=False,
        amount=Decimal("10.00"),
        currency="EUR",
        description="test row",
    )


def _config(make_config: Callable[[str], Config]) -> Config:
    return make_config(STATEMENT_CONFIG)


EXPECTED_ACCOUNTING = {
    # account: (input rows, exported, merged, excluded reasons)
    "Shared": (12, 7, 2, {"pocket_side_row": 2, "reverted": 1}),
    "Revolut": (7, 5, 2, {}),
    "Safety": (6, 0, 2, {"mirrored_by_main_export": 2, "savings_internal": 2}),
    "Wise": (4, 3, 1, {}),
    "Black": (2, 2, 0, {}),
    "Platinum": (1, 1, 0, {}),
    "BBVA": (14, 14, 0, {}),
    "Santander": (4, 4, 0, {}),
}


def _by_account(result: ConvertResult) -> dict[str, FileResult]:
    return {f.statement.account: f for f in result.files}


def _csv_lines(result: ConvertResult) -> list[list[str]]:
    with result.output.open(encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def _assert_balanced(result: ConvertResult) -> None:
    for file in result.files:
        accounting = file.accounting
        assert accounting.balanced, file.statement.file.name
        assert accounting.skipped == 0
        assert accounting.merged == len(file.merged)
        assert accounting.exported == len(file.exported)


def test_run_convert_over_statement_folder(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = _config(make_config)

    result = run_convert(statement_folder, config)

    assert len(result.files) == 8
    _assert_balanced(result)
    by_account = _by_account(result)
    for account, (source_rows, exported, merged, reasons) in EXPECTED_ACCOUNTING.items():
        accounting = by_account[account].accounting
        assert accounting.source_rows == source_rows, account
        assert accounting.exported == exported, account
        assert accounting.merged == merged, account
        assert by_account[account].reasons == reasons, account

    assert result.mismatched is False
    assert result.dry_run is False
    assert result.written is True
    assert result.output == statement_folder / "moneywiz_import.csv"

    lines = _csv_lines(result)
    assert lines[0] == COLUMNS
    assert len(lines) == 1 + 41
    assert len(result.export_rows) == 36 + 5
    assert len({row.memo for row in result.export_rows}) == 41
    assert all(row.memo.startswith("smt:") for row in result.export_rows)


def test_integration_lumps(statement_folder: Path, make_config: Callable[[str], Config]) -> None:
    result = run_convert(statement_folder, _config(make_config), dry_run=True)

    lumps = {
        (lump.kind, lump.account, lump.counterpart, lump.amount, lump.payee)
        for lump in result.lumps
    }
    assert lumps == {
        ("roundups", "Shared", "Travel", Decimal("-0.50"), None),
        ("interest", "Travel", None, Decimal("0.01"), "Revolut"),
        ("roundups", "Revolut", "Safety", Decimal("-0.40"), None),
        ("interest", "Safety", None, Decimal("0.13"), "Revolut"),
        ("fee", "Safety", None, Decimal("-0.01"), "Revolut"),
    }
    lump_rows = {(r.account, r.amount): r for r in result.export_rows if r.account == "Travel"}
    assert lump_rows[("Travel", Decimal("0.01"))].payee == "Revolut"


def test_integration_transfers(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    result = run_convert(statement_folder, _config(make_config), dry_run=True)

    with_transfers = {(r.account, r.amount, r.transfers) for r in result.export_rows if r.transfers}
    assert with_transfers == {
        ("Revolut", Decimal("-44.00"), "Wise"),
        ("Wise", Decimal("-42.00"), "Revolut"),
        ("Revolut", Decimal("-200.00"), "Safety"),
        ("Shared", Decimal("5.00"), "Travel"),
        ("Platinum", Decimal("-436"), "Black"),
        ("Shared", Decimal("-0.50"), "Travel"),
        ("Revolut", Decimal("-0.40"), "Safety"),
    }
    for row in result.export_rows:
        if row.transfers:
            assert row.payee == ""
    assert result.link_notes == (
        "counterpart not found in Black for Platinum 2026-09-24T13:25:36 -436",
    )
    platinum = next(t for t in result.transfers if t.source == "Platinum")
    assert (platinum.destination, platinum.incoming) == ("Black", None)

    pairs = [t for t in result.transfers if t.outgoing is not None and t.incoming is not None]
    assert len(pairs) == 2
    merged_legs = {(cr.row.account, cr.row.amount) for f in result.files for cr in f.merged}
    assert ("Wise", Decimal("44.00")) in merged_legs
    assert ("Revolut", Decimal("42.00")) in merged_legs


def test_integration_unmatched_and_payees(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    result = run_convert(statement_folder, _config(make_config), dry_run=True)

    assert {(cr.row.account, cr.row.amount) for cr in result.unmatched} == {
        ("Shared", Decimal("100.00")),
        ("Revolut", Decimal("-50.00")),
        ("BBVA", Decimal("200")),
        ("BBVA", Decimal("80")),
    }
    unmatched_rows = {
        (r.account, r.amount) for r in result.export_rows if r.payee == "Unmatched transfer"
    }
    assert unmatched_rows == {(cr.row.account, cr.row.amount) for cr in result.unmatched}

    def only(account: str, description_part: str) -> str:
        (row,) = [
            r
            for r in result.export_rows
            if r.account == account and description_part in (r.description or r.payee)
        ]
        return row.payee

    assert only("Shared", "Metal plan fee") == "Revolut"
    assert only("Wise", "Cashback") == "Wise"
    assert only("Black", "Проценты на остаток") == "TBank"

    payees = {r.payee for r in result.export_rows}
    assert {"Alex Example", "Partner Person", "Sample Utility Company", "test user"} <= payees


def _without_pockets(config_toml: str) -> str:
    blocks = config_toml.split("\n\n")
    kept = [block for block in blocks if not block.startswith("[pockets.")]
    assert len(kept) == len(blocks) - 2
    return "\n\n".join(kept)


def test_without_pockets_config_every_pocket_row_is_a_hidden_pocket(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    result = run_convert(
        statement_folder, make_config(_without_pockets(STATEMENT_CONFIG)), dry_run=True
    )

    _assert_balanced(result)
    by_account = _by_account(result)
    assert by_account["Shared"].reasons == {"hidden_pocket": 5, "reverted": 1}
    assert by_account["Revolut"].reasons == {"hidden_pocket": 2}
    assert all(lump.pocket is None for lump in result.lumps)
    assert {lump.account for lump in result.lumps} == {"Safety"}
    assert not any(t.destination in {"Travel", "Safety"} for t in result.transfers)


def test_accounting_is_balanced_in_every_variant(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    for config_toml in (
        STATEMENT_CONFIG,
        _without_pockets(STATEMENT_CONFIG),
    ):
        result = run_convert(statement_folder, make_config(config_toml), dry_run=True)
        _assert_balanced(result)
        for file in result.files:
            accounted = {id(cr) for cr in (*file.exported, *file.merged)}
            accounted |= {id(ex.row) for ex in file.excluded}
            assert len(accounted) == len(file.exported) + len(file.merged) + len(file.excluded)


def test_lump_memo_tags_are_stable_across_runs(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = _config(make_config)

    first = run_convert(statement_folder, config, dry_run=True)
    second = run_convert(statement_folder, config, dry_run=True)

    assert [r.memo for r in first.export_rows] == [r.memo for r in second.export_rows]
    roundups = [r.memo for r in first.export_rows if "round-up" in r.description]
    assert len(roundups) == 2
    assert roundups[0] != roundups[1]


def test_run_convert_dry_run_writes_nothing(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = _config(make_config)
    original = (statement_folder / "moneywiz_import.csv").read_text()

    result = run_convert(statement_folder, config, dry_run=True)

    assert result.dry_run is True
    assert result.written is False
    assert (statement_folder / "moneywiz_import.csv").read_text() == original


def test_run_convert_output_override(
    statement_folder: Path, make_config: Callable[[str], Config], tmp_path: Path
) -> None:
    config = _config(make_config)
    target = tmp_path / "custom.csv"

    result = run_convert(statement_folder, config, output=target)

    assert result.output == target
    assert result.written is True
    assert target.exists()


def test_run_convert_balance_mismatch_blocks_write(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = _config(make_config)
    shared = statement_folder / "revolut_shared.csv"
    shared.write_text(shared.read_text().replace("164.01", "999.99"))
    original = (statement_folder / "moneywiz_import.csv").read_text()

    result = run_convert(statement_folder, config)

    assert result.mismatched is True
    assert result.written is False
    assert (statement_folder / "moneywiz_import.csv").read_text() == original

    all_mismatches = [m for f in result.files for m in f.mismatches]
    assert len(all_mismatches) == 1
    assert all_mismatches[0].row.line == 13


def test_run_convert_allow_balance_mismatch_writes(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = _config(make_config)
    shared = statement_folder / "revolut_shared.csv"
    shared.write_text(shared.read_text().replace("164.01", "999.99"))

    result = run_convert(statement_folder, config, allow_balance_mismatch=True)

    assert result.mismatched is True
    assert result.written is True
    assert result.output.exists()


def test_accounting_is_unbalanced_when_input_rows_exceed_accounted_rows() -> None:
    row = _row()
    statement = ParsedStatement(
        file=Path("revolut.csv"),
        bank="revolut",
        kind="current",
        account="Main",
        rows=(row,),
        input_rows=2,
    )

    classified = ClassifiedRow(row=row, kind="purchase", evidence="test")
    result = FileResult(
        statement=statement,
        classified=(classified,),
        exported=(classified,),
        merged=(),
        skipped=(),
        excluded=(),
        mismatches=(),
    )

    assert result.accounting.source_rows == 2
    assert result.accounting.balanced is False


def test_run_convert_lists_files_with_unbalanced_accounting(
    statement_folder: Path, make_config: Callable[[str], Config], monkeypatch: pytest.MonkeyPatch
) -> None:
    inflate_wise_input_rows(monkeypatch)

    result = run_convert(statement_folder, _config(make_config), dry_run=True)

    assert [f.statement.file.name for f in result.unbalanced] == ["wise.csv"]


WISE_ONLY = '[[accounts]]\nbank = "wise"\nmoneywiz = "Wise"\nfile = "wise*"\n'


def test_run_convert_excludes_rows_already_exported_by_an_earlier_file(
    tmp_path: Path, make_config: Callable[[str], Config]
) -> None:
    folder = tmp_path / "2026_09"
    folder.mkdir()
    shutil.copy(FIXTURES / "wise.csv", folder / "wise.csv")
    shutil.copy(FIXTURES / "wise.csv", folder / "wise_copy.csv")

    result = run_convert(folder, make_config(WISE_ONLY), dry_run=True)

    assert len(result.export_rows) == 4
    first, second = result.files
    assert first.statement.file.name == "wise.csv"
    assert first.accounting.exported == 4
    assert second.accounting.exported == 0
    assert second.reasons == {"duplicate_of_other_file": 4}
    assert all(f.accounting.balanced for f in result.files)


REVOLUT_TWICE = """\
Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance
Card Payment,Current,2026-08-01 10:00:00,2026-08-01 10:00:00,Coffee,-3.50,0.00,EUR,COMPLETED,
Card Payment,Current,2026-08-01 10:00:00,2026-08-01 10:00:00,Coffee,-3.50,0.00,EUR,COMPLETED,
"""


def test_run_convert_keeps_identical_rows_within_one_file(
    tmp_path: Path, make_config: Callable[[str], Config]
) -> None:
    folder = tmp_path / "2026_09"
    folder.mkdir()
    (folder / "revolut_shared.csv").write_text(REVOLUT_TWICE)

    result = run_convert(folder, make_config(STATEMENT_CONFIG), dry_run=True)

    assert len(result.export_rows) == 2
    assert result.export_rows[0].memo != result.export_rows[1].memo
    assert result.files[0].excluded == ()


def _duplicate_revolut_row(monkeypatch: pytest.MonkeyPatch, description: str) -> None:
    """Make the Revolut parser emit one row of the "Revolut" statement twice, same line."""
    parse_current = PARSERS[("revolut", "current")]

    def parse(path: Path, account: str, identity: str | None) -> ParsedStatement:
        statement = parse_current(path, account, identity)
        if account != "Revolut":
            return statement
        (row,) = [row for row in statement.rows if row.description == description]
        copy = replace(row)
        return replace(statement, rows=(*statement.rows, copy), input_rows=statement.input_rows + 1)

    monkeypatch.setitem(PARSERS, ("revolut", "current"), parse)


def test_value_equal_rows_are_tracked_one_by_one(
    statement_folder: Path, make_config: Callable[[str], Config], monkeypatch: pytest.MonkeyPatch
) -> None:
    _duplicate_revolut_row(monkeypatch, "Payment from Sample Owner")

    result = run_convert(statement_folder, _config(make_config), dry_run=True)

    _assert_balanced(result)
    revolut = _by_account(result)["Revolut"]
    assert (revolut.accounting.source_rows, revolut.accounting.exported) == (8, 6)
    assert revolut.accounting.merged == 2
    copies = [cr for cr in revolut.classified if cr.row.description == "Payment from Sample Owner"]
    assert len(copies) == 2
    assert copies[0] == copies[1]
    unmatched_ids = {id(cr) for cr in result.unmatched}
    assert [id(cr) in unmatched_ids for cr in copies].count(True) == 1
    assert sum(1 for cr in revolut.merged if cr.row.description == "Payment from Sample Owner") == 1


# --- MoneyWiz snapshot: lump coverage and the account check ------------------------


def _lump_notes(result: ConvertResult) -> list[str]:
    return [row.memo for row in result.export_rows if "smt-lump:" in row.memo]


def test_lump_overlapping_an_earlier_one_exports_only_the_tail(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)
    first = run_convert(roundups_folder, config, dry_run=True)
    (first_lump,) = first.lumps
    assert len(first_lump.rows) == 3
    earlier = f"smt-lump:{first_lump.key}:20260802T100000"
    snapshot = snapshot_of(exported_names(first), [f"smt:000000000000 {earlier}"])

    result = run_convert(roundups_folder, config, dry_run=True, snapshot=snapshot)

    (lump,) = result.lumps
    assert [cr.row.line for cr in lump.rows] == [7]
    assert lump.amount == Decimal("-0.30")
    (file,) = result.files
    assert [cr.row.line for cr in file.skipped] == [3, 5]
    assert file.accounting.skipped == 2
    assert file.accounting.merged == 1
    assert file.accounting.exported == 1
    assert file.accounting.balanced
    assert not {id(cr) for cr in file.skipped} & {id(cr) for cr in file.merged}
    assert [(r.amount, r.transfers) for r in result.export_rows] == [
        (Decimal("-3.50"), ""),
        (Decimal("-0.30"), "Travel"),
    ]
    assert result.moneywiz_checked is True


def test_lump_fully_covered_by_an_earlier_one_exports_nothing(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)
    first = run_convert(roundups_folder, config, dry_run=True)
    snapshot = snapshot_of(exported_names(first), _lump_notes(first))

    result = run_convert(roundups_folder, config, dry_run=True, snapshot=snapshot)

    assert result.lumps == ()
    (file,) = result.files
    assert file.accounting.skipped == 3
    assert file.accounting.merged == 0
    assert file.accounting.balanced
    assert [r.amount for r in result.export_rows] == [Decimal("-3.50")]


def test_snapshot_filters_nothing_but_lumps(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = _config(make_config)
    plain = run_convert(statement_folder, config, dry_run=True)
    plain_memos = [row.memo for row in plain.export_rows if "smt-lump:" not in row.memo]
    snapshot = snapshot_of(exported_names(plain), plain_memos)

    result = run_convert(statement_folder, config, dry_run=True, snapshot=snapshot)

    assert result.export_rows == plain.export_rows
    assert result.moneywiz_checked is True
    _assert_balanced(result)


def test_snapshot_with_unrelated_lump_markers_changes_nothing(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = _config(make_config)
    plain = run_convert(statement_folder, config, dry_run=True)
    snapshot = snapshot_of(exported_names(plain), ["smt-lump:00000000:20260101T000000"])

    result = run_convert(statement_folder, config, dry_run=True, snapshot=snapshot)

    assert result.export_rows == plain.export_rows
    assert [f.accounting.skipped for f in result.files] == [0] * len(result.files)


def test_without_a_snapshot_moneywiz_is_not_checked(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    result = run_convert(statement_folder, _config(make_config), dry_run=True)

    assert result.moneywiz_checked is False


def test_missing_account_name_fails_before_writing(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = _config(make_config)
    names = exported_names(run_convert(statement_folder, config, dry_run=True))
    snapshot = snapshot_of(names - {"Travel", "Wise"})
    target = statement_folder / "out.csv"

    with pytest.raises(ConfigError) as caught:
        run_convert(statement_folder, config, output=target, snapshot=snapshot)

    message = str(caught.value)
    assert "'Travel'" in message
    assert "'Wise'" in message
    assert "'Shared'" not in message
    assert "new accounts" in message
    assert not target.exists()


def test_missing_account_name_fails_in_a_dry_run_too(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = _config(make_config)
    names = exported_names(run_convert(statement_folder, config, dry_run=True))

    with pytest.raises(ConfigError, match="'Safety'"):
        run_convert(
            statement_folder, config, dry_run=True, snapshot=snapshot_of(names - {"Safety"})
        )


def test_account_in_the_transfers_column_only_is_checked_too(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)

    with pytest.raises(ConfigError, match="'Travel'"):
        run_convert(roundups_folder, config, dry_run=True, snapshot=snapshot_of(["Shared"]))


def test_account_names_match_the_store_ignoring_case_and_spacing(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(ROUNDUPS_CONFIG)

    result = run_convert(
        roundups_folder, config, dry_run=True, snapshot=snapshot_of(["shared", "TRAVEL "])
    )

    assert result.moneywiz_checked is True


def test_a_zero_amount_row_is_excluded_because_moneywiz_drops_it(
    roundups_folder: Path, make_config: Callable[[str], Config]
) -> None:
    zero = (
        "Card Payment,Current,2026-08-03 11:00:00,2026-08-03 11:00:00,Bonus Points,"
        "0.00,0.00,EUR,COMPLETED,95.90"
    )
    (roundups_folder / "revolut_shared.csv").write_text(ROUNDUPS_CSV + "\n" + zero)

    result = run_convert(roundups_folder, make_config(ROUNDUPS_CONFIG), dry_run=True)

    (file_result,) = result.files
    assert file_result.reasons.get("zero_amount") == 1
    assert all(row.amount != 0 for row in result.export_rows)
    assert file_result.accounting.balanced
