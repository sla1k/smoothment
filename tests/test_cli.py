import csv
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from smoothment.cli import app
from smoothment.config import Config
from smoothment.convert import run_convert
from tests.conftest import ROUNDUPS_CONFIG, STATEMENT_CONFIG, MakeDb, inflate_wise_input_rows
from tests.moneywiz_fixture import FxAccount, FxCategory, FxTransaction
from tests.snapshot_fixtures import imported_snapshot, store_rows

runner = CliRunner()
WIDE = {"COLUMNS": "200"}


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == "smoothment 0.1.0"


CONFIG = '[owner]\nnames = ["A"]\n[moneywiz]\ndb = "{db}"\n'


def _config(tmp_path: Path, db: Path) -> Path:
    cfg = tmp_path / "smoothment.toml"
    cfg.write_text(CONFIG.format(db=db.as_posix()))
    return cfg


def test_probe_write_uses_first_expense_leaf_and_prints_instructions(
    moneywiz_db: MakeDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    db = moneywiz_db(
        [FxAccount(1, "Revolut")],
        [FxCategory(10, "Food"), FxCategory(11, "Groceries", parent=10)],
        [],
        [],
    )
    cfg = _config(tmp_path, db)
    result = runner.invoke(app, ["probe", "write", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "smoothment_probe.csv").exists()
    assert "Food > Groceries" in (tmp_path / "smoothment_probe.csv").read_text()
    assert "SMT Probe RUB" in result.output


def test_probe_write_without_store_needs_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    cfg = _config(tmp_path, tmp_path / "missing.sqlite")
    result = runner.invoke(app, ["probe", "write", "--config", str(cfg)])
    assert result.exit_code == 2
    result = runner.invoke(app, ["probe", "write", "--config", str(cfg), "--category", "X > Y"])
    assert result.exit_code == 0, result.output


def test_probe_check_writes_overlay(
    moneywiz_db: MakeDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    eur, eur2, rub = 1, 2, 3
    db = moneywiz_db(
        [
            FxAccount(eur, "SMT Probe EUR"),
            FxAccount(eur2, "SMT Probe EUR 2"),
            FxAccount(rub, "SMT Probe RUB", "RUB"),
        ],
        [],
        [],
        [
            FxTransaction(100, 48, eur, -12.34, datetime(2026, 1, 5), notes="smt:probe:plain"),
            FxTransaction(101, 47, eur, -20.0, datetime(2026, 1, 6), recipient_account=eur2),
            FxTransaction(102, 46, eur2, 20.0, datetime(2026, 1, 6), sender_account=eur),
        ],
    )
    cfg = _config(tmp_path, db)
    result = runner.invoke(app, ["probe", "check", "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "smoothment.probe.toml").exists()
    assert "single_leg_creates_reciprocal" in result.output


def test_probe_check_refuses_when_moneywiz_runs(
    moneywiz_db: MakeDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", lambda: ["MoneyWiz"])
    db = moneywiz_db([FxAccount(1, "SMT Probe EUR")], [], [], [])
    cfg = _config(tmp_path, db)
    result = runner.invoke(app, ["probe", "check", "--config", str(cfg)])
    assert result.exit_code == 2
    assert "running" in result.output.lower()


STATEMENT_CONFIG_NO_WISE = "\n".join(
    block for block in STATEMENT_CONFIG.split("\n\n") if 'bank = "wise"' not in block
)


def test_convert_dry_run_names_files_and_writes_nothing(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)
    original = (statement_folder / "moneywiz_import.csv").read_text()

    result = runner.invoke(
        app,
        [
            "convert",
            str(statement_folder),
            "--config",
            str(config.path),
            "--no-moneywiz",
            "--dry-run",
        ],
        env=WIDE,
    )

    assert result.exit_code == 0, result.output
    for name in (
        "revolut_shared.csv",
        "revolut_saves.csv",
        "revolut_travel.csv",
        "wise.csv",
        "tbank_two_accounts.ofx",
        "bbva.xlsx",
        "santander.xlsx",
        "random.csv",
    ):
        assert name in result.output, result.output
    assert "pocket_side_row" in result.output
    assert "41 rows ready; nothing written (dry run)" in result.output
    assert "Unmatched transfers" in result.output
    assert (statement_folder / "moneywiz_import.csv").read_text() == original


def test_convert_writes_csv_with_smt_tags(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)

    result = runner.invoke(
        app,
        ["convert", str(statement_folder), "--config", str(config.path), "--no-moneywiz"],
        env=WIDE,
    )

    assert result.exit_code == 0, result.output
    assert "wrote 41 rows to" in result.output
    assert "moneywiz_import.csv" in result.output
    content = (statement_folder / "moneywiz_import.csv").read_text()
    memos = [line[-1] for line in csv.reader(content.splitlines())][1:]
    assert len(memos) == 41
    assert all(memo.startswith("smt:") for memo in memos)
    assert content.count("smt:") == 41 + 2


def test_convert_reads_the_config_next_to_the_statement_folder(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    make_config(STATEMENT_CONFIG)

    result = runner.invoke(
        app, ["convert", str(statement_folder), "--no-moneywiz", "--dry-run"], env=WIDE
    )

    assert result.exit_code == 0, result.output
    assert "41 rows ready; nothing written (dry run)" in result.output


def test_convert_without_a_config_next_to_the_folder_names_the_path(tmp_path: Path) -> None:
    folder = tmp_path / "2026_09"
    folder.mkdir()

    result = runner.invoke(app, ["convert", str(folder), "--no-moneywiz"], env=WIDE)

    assert result.exit_code == 2
    assert "smoothment.toml" in result.output
    assert "--config" in result.output


def test_probe_write_reads_the_config_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _config(tmp_path, tmp_path / "missing.sqlite")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["probe", "write", "--category", "X > Y"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "smoothment_probe.csv").exists()


def test_convert_exports_one_leg_per_transfer_whatever_the_probe_answered(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    probe = "[moneywiz]\ntwo_legs_link_once = false\nsingle_leg_creates_reciprocal = false\n"
    config = make_config(probe + STATEMENT_CONFIG)

    result = runner.invoke(
        app,
        [
            "convert",
            str(statement_folder),
            "--config",
            str(config.path),
            "--no-moneywiz",
            "--dry-run",
        ],
        env=WIDE,
    )

    assert result.exit_code == 0, result.output
    assert "probe" not in result.output
    assert "41 rows ready" in result.output


def test_convert_balance_mismatch_blocks_write_and_exits_1(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)
    shared = statement_folder / "revolut_shared.csv"
    shared.write_text(shared.read_text().replace("164.01", "999.99"))

    result = runner.invoke(
        app,
        ["convert", str(statement_folder), "--config", str(config.path), "--no-moneywiz"],
        env=WIDE,
    )

    assert result.exit_code == 1, result.output
    assert "balance mismatch" in result.output
    assert "row 13" in result.output
    assert "pending" in result.output
    assert "--allow-balance-mismatch" in result.output
    assert "was not written" in result.output


def test_convert_unmapped_file_exits_2(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG_NO_WISE)

    result = runner.invoke(
        app,
        ["convert", str(statement_folder), "--config", str(config.path), "--no-moneywiz"],
        env=WIDE,
    )

    assert result.exit_code == 2, result.output
    assert "wise.csv" in result.output
    assert "[[accounts]]" in result.output


def test_convert_missing_folder_exits_2(
    tmp_path: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)
    missing = tmp_path / "does_not_exist"

    result = runner.invoke(
        app,
        ["convert", str(missing), "--config", str(config.path), "--no-moneywiz"],
        env=WIDE,
    )

    assert result.exit_code == 2, result.output


def test_convert_report_shows_full_name_of_bracketed_unrecognized_file(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)
    (statement_folder / "notes[1].csv").write_text("a,b,c\n")

    result = runner.invoke(
        app,
        [
            "convert",
            str(statement_folder),
            "--config",
            str(config.path),
            "--no-moneywiz",
            "--dry-run",
        ],
        env=WIDE,
    )

    assert result.exit_code == 0, result.output
    assert "notes[1].csv" in result.output


def test_convert_row_accounting_mismatch_exits_1(
    statement_folder: Path, make_config: Callable[[str], Config], monkeypatch: pytest.MonkeyPatch
) -> None:
    inflate_wise_input_rows(monkeypatch)
    config = make_config(STATEMENT_CONFIG)

    result = runner.invoke(
        app,
        [
            "convert",
            str(statement_folder),
            "--config",
            str(config.path),
            "--no-moneywiz",
            "--dry-run",
        ],
        env=WIDE,
    )

    assert result.exit_code == 1, result.output
    assert "row accounting mismatch" in result.output
    assert "wise.csv" in result.output


def test_convert_drifted_revolut_header_is_a_format_error(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)
    shared = statement_folder / "revolut_shared.csv"
    lines = shared.read_text().splitlines()
    shared.write_text("\n".join(line + ",x" for line in lines) + "\n")

    result = runner.invoke(
        app,
        [
            "convert",
            str(statement_folder),
            "--config",
            str(config.path),
            "--no-moneywiz",
            "--dry-run",
        ],
        env=WIDE,
    )

    assert result.exit_code == 2, result.output
    assert "revolut_shared.csv row 1, column header" in result.output


def test_convert_dry_run_balance_mismatch_says_would_not_be_written(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)
    shared = statement_folder / "revolut_shared.csv"
    shared.write_text(shared.read_text().replace("164.01", "999.99"))

    result = runner.invoke(
        app,
        [
            "convert",
            str(statement_folder),
            "--config",
            str(config.path),
            "--no-moneywiz",
            "--dry-run",
        ],
        env=WIDE,
    )

    assert result.exit_code == 1, result.output
    assert "would not be written" in result.output
    assert "--allow-balance-mismatch" in result.output


def test_convert_output_into_missing_directory_exits_2(
    statement_folder: Path, make_config: Callable[[str], Config], tmp_path: Path
) -> None:
    config = make_config(STATEMENT_CONFIG)
    target = tmp_path / "missing" / "out.csv"

    result = runner.invoke(
        app,
        [
            "convert",
            str(statement_folder),
            "--config",
            str(config.path),
            "--no-moneywiz",
            "--output",
            str(target),
        ],
        env=WIDE,
    )

    assert result.exit_code == 2, result.output
    assert "error:" in result.output
    assert "out.csv" in result.output


# --- convert reads the MoneyWiz store ---------------------------------------------

STORE_ACCOUNTS = (
    "Shared",
    "Revolut",
    "Safety",
    "Wise",
    "Black",
    "Platinum",
    "BBVA",
    "Santander",
    "Travel",
)


def _store(
    moneywiz_db: MakeDb,
    names: tuple[str, ...] = STORE_ACCOUNTS,
    transactions: list[FxTransaction] | None = None,
) -> Path:
    accounts = [FxAccount(index, name) for index, name in enumerate(names, start=1)]
    return moneywiz_db(accounts, [], [], transactions or [])


def _config_with_store(make_config: Callable[[str], Config], db: Path) -> Config:
    return make_config(f'[moneywiz]\ndb = "{db.as_posix()}"\n' + STATEMENT_CONFIG)


def test_convert_reads_the_store_by_default_and_checks_account_names(
    statement_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    config = _config_with_store(make_config, _store(moneywiz_db))

    result = runner.invoke(
        app,
        ["convert", str(statement_folder), "--config", str(config.path), "--dry-run"],
        env=WIDE,
    )

    assert result.exit_code == 0, result.output
    assert "41 rows ready; nothing written (dry run)" in result.output
    assert "were not checked" not in result.output


def test_convert_skips_a_lump_the_store_already_holds(
    statement_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    earlier = FxTransaction(
        100, 47, 1, -0.5, datetime(2026, 8, 1, 10), notes="smt-lump:993feaaa:20260801T100005"
    )
    config = _config_with_store(make_config, _store(moneywiz_db, transactions=[earlier]))

    result = runner.invoke(
        app,
        ["convert", str(statement_folder), "--config", str(config.path)],
        env=WIDE,
    )

    assert result.exit_code == 0, result.output
    assert "wrote 40 rows to" in result.output
    assert "Covered by an earlier lump" in result.output
    content = (statement_folder / "moneywiz_import.csv").read_text()
    assert "smt-lump:993feaaa" not in content


def test_convert_missing_account_in_the_store_exits_2_and_writes_nothing(
    statement_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    names = tuple(name for name in STORE_ACCOUNTS if name != "Travel")
    config = _config_with_store(make_config, _store(moneywiz_db, names))
    original = (statement_folder / "moneywiz_import.csv").read_text()

    result = runner.invoke(
        app,
        ["convert", str(statement_folder), "--config", str(config.path)],
        env=WIDE,
    )

    assert result.exit_code == 2, result.output
    assert "Travel" in result.output
    assert "new accounts" in result.output
    assert (statement_folder / "moneywiz_import.csv").read_text() == original


def test_convert_refuses_while_moneywiz_runs(
    statement_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", lambda: ["MoneyWiz"])
    config = _config_with_store(make_config, _store(moneywiz_db))

    result = runner.invoke(
        app,
        ["convert", str(statement_folder), "--config", str(config.path), "--dry-run"],
        env=WIDE,
    )

    assert result.exit_code == 2, result.output
    assert "running" in result.output.lower()
    assert "rows ready" not in result.output


def test_convert_allow_running_reads_the_store_anyway(
    statement_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", lambda: ["MoneyWiz"])
    config = _config_with_store(make_config, _store(moneywiz_db))

    result = runner.invoke(
        app,
        [
            "convert",
            str(statement_folder),
            "--config",
            str(config.path),
            "--dry-run",
            "--allow-running",
        ],
        env=WIDE,
    )

    assert result.exit_code == 0, result.output
    assert "41 rows ready" in result.output
    assert "were not checked" not in result.output


def test_convert_no_moneywiz_warns_and_does_not_touch_the_store(
    statement_folder: Path,
    make_config: Callable[[str], Config],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", lambda: ["MoneyWiz"])
    config = _config_with_store(make_config, tmp_path / "missing.sqlite")

    result = runner.invoke(
        app,
        [
            "convert",
            str(statement_folder),
            "--config",
            str(config.path),
            "--dry-run",
            "--no-moneywiz",
        ],
        env=WIDE,
    )

    assert result.exit_code == 0, result.output
    assert "lumps may repeat earlier ones" in result.output
    assert "account names were not checked" in result.output
    assert "41 rows ready" in result.output


def test_convert_two_live_accounts_with_one_name_exit_2_cleanly(
    statement_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    accounts = [FxAccount(index, name) for index, name in enumerate(STORE_ACCOUNTS, start=1)]
    accounts.append(FxAccount(99, "Wise"))
    config = _config_with_store(make_config, moneywiz_db(accounts, [], [], []))

    result = runner.invoke(
        app,
        ["convert", str(statement_folder), "--config", str(config.path), "--dry-run"],
        env=WIDE,
    )

    assert result.exit_code == 2, result.output
    assert "error:" in result.output
    assert "Wise" in result.output
    assert "Traceback" not in result.output
    assert isinstance(result.exception, SystemExit)


# --- verify ---------------------------------------------------------------------------


def _verify_setup(
    roundups_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    drop_amount: str | None = None,
) -> Config:
    plain = make_config(ROUNDUPS_CONFIG)
    result = run_convert(roundups_folder, plain, dry_run=True)
    snapshot = imported_snapshot(result, {"Shared": Decimal("100.00")})
    accounts, transactions = store_rows(snapshot)
    if drop_amount is not None:
        transactions = [t for t in transactions if t.amount != float(drop_amount)]
    db = moneywiz_db(accounts, [], [], transactions)
    return make_config(f'[moneywiz]\ndb = "{db.as_posix()}"\n' + ROUNDUPS_CONFIG)


def test_verify_clean_import_exits_0(
    roundups_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    config = _verify_setup(roundups_folder, make_config, moneywiz_db)

    result = runner.invoke(
        app, ["verify", str(roundups_folder), "--config", str(config.path)], env=WIDE
    )

    assert result.exit_code == 0, result.output
    assert "Nothing to fix" in result.output
    assert "Balances" in result.output
    assert "Missing in MoneyWiz" not in result.output


def test_verify_reports_a_missing_row_and_exits_1(
    roundups_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    config = _verify_setup(roundups_folder, make_config, moneywiz_db, drop_amount="-3.50")

    result = runner.invoke(
        app, ["verify", str(roundups_folder), "--config", str(config.path)], env=WIDE
    )

    assert result.exit_code == 1, result.output
    assert "Missing in MoneyWiz" in result.output
    assert "Coffee Corner" in result.output
    assert "-3.50" in result.output
    assert "Nothing to fix" not in result.output
    assert not (roundups_folder / "moneywiz_import.csv").exists()


def test_verify_refuses_while_moneywiz_runs(
    roundups_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    config = _verify_setup(roundups_folder, make_config, moneywiz_db)
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", lambda: ["MoneyWiz"])

    refused = runner.invoke(
        app, ["verify", str(roundups_folder), "--config", str(config.path)], env=WIDE
    )
    allowed = runner.invoke(
        app,
        ["verify", str(roundups_folder), "--config", str(config.path), "--allow-running"],
        env=WIDE,
    )

    assert refused.exit_code == 2, refused.output
    assert "running" in refused.output.lower()
    assert allowed.exit_code == 0, allowed.output


def test_verify_unmapped_file_exits_2(
    statement_folder: Path,
    make_config: Callable[[str], Config],
    moneywiz_db: MakeDb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    (statement_folder / "wise.csv").rename(statement_folder / "unknown_bank.csv")
    config = _config_with_store(make_config, _store(moneywiz_db))

    result = runner.invoke(
        app, ["verify", str(statement_folder), "--config", str(config.path)], env=WIDE
    )

    assert result.exit_code == 2, result.output
    assert "error:" in result.output
