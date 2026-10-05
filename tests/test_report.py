from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from rich.console import Console

from smoothment.classify.model import ClassifiedRow
from smoothment.config import Config
from smoothment.convert import ConvertResult, run_convert
from smoothment.link import Transfer
from smoothment.report import render_report, unmatched_why
from tests.classify_fixtures import make_row
from tests.conftest import STATEMENT_CONFIG, inflate_wise_input_rows
from tests.snapshot_fixtures import exported_names, snapshot_of

REVOLUT_CSV = """\
Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance
Card,Current,2026-08-01 10:00:00,2026-08-01 10:00:00,Coffee,-3.50,0.00,EUR,COMPLETED,96.50
Card,Current,2026-08-02 10:00:00,2026-08-02 10:00:00,Later,-1.00,0.00,EUR,COMPLETED,999.99
Card,Current,2026-08-03 09:00:00,,Coffee [Mom],-9.99,0.00,EUR,PENDING,
"""


def test_render_report_escapes_markup_in_file_names_and_descriptions(
    tmp_path: Path, make_config: Callable[[str], Config]
) -> None:
    folder = tmp_path / "2026_09"
    folder.mkdir()
    (folder / "revolut_[shared].csv").write_text(REVOLUT_CSV)
    config = make_config(
        '[[accounts]]\nbank = "revolut"\nmoneywiz = "Shared"\nfile = "revolut_*.csv"\n'
    )

    result = run_convert(folder, config, dry_run=True)
    console = Console(record=True, width=200)

    render_report(result, console)
    output = console.export_text()

    assert "revolut_[shared].csv" in output
    assert "[Mom]" in output


def test_render_report_marks_file_with_row_accounting_mismatch(
    statement_folder: Path, make_config: Callable[[str], Config], monkeypatch: pytest.MonkeyPatch
) -> None:
    inflate_wise_input_rows(monkeypatch)
    result = run_convert(statement_folder, make_config(STATEMENT_CONFIG), dry_run=True)
    console = Console(record=True, width=200)

    render_report(result, console)
    output = console.export_text()

    assert "row accounting mismatch: wise.csv: 5 input rows, 4 accounted" in output


def test_render_report_counts_unrecognized_files_in_the_closing_line(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    result = run_convert(statement_folder, make_config(STATEMENT_CONFIG), dry_run=True)
    console = Console(record=True, width=200)

    render_report(result, console)
    output = console.export_text()

    closing = output.strip().splitlines()[-1]
    assert closing == (
        "41 rows ready; nothing written (dry run); "
        "5 lumps, 7 transfers, 4 unmatched; 1 unrecognized file(s)"
    )


def test_render_report_prints_unrecognized_lines_in_a_warning_colour(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    result = run_convert(statement_folder, make_config(STATEMENT_CONFIG), dry_run=True)
    console = Console(record=True, width=200, force_terminal=True, color_system="standard")

    render_report(result, console)
    output = console.export_text(styles=True)

    line = next(line for line in output.splitlines() if "random.csv" in line)
    assert "\x1b[33m" in line


def _render(statement_folder: Path, config: Config) -> str:
    result = run_convert(statement_folder, config, dry_run=True)
    console = Console(record=True, width=300)
    render_report(result, console)
    return console.export_text()


def _table_rows(output: str, title: str) -> list[list[str]]:
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == title)
    rows: list[list[str]] = []
    for line in lines[start + 1 :]:
        if line.startswith("\u2514"):
            break
        if line.startswith("\u2502"):
            rows.append([cell.strip() for cell in line.strip("\u2502").split("\u2502")])
    return rows


def test_render_report_lists_unmatched_transfers_before_the_statements_table(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    output = _render(statement_folder, make_config(STATEMENT_CONFIG))

    assert output.index("Unmatched transfers") < output.index("Balance")
    rows = _table_rows(output, "Unmatched transfers")
    assert [row[:4] for row in rows] == [
        ["BBVA", "2025-11-24", "80.00", "Transfer received"],
        ["BBVA", "2025-12-02", "200.00", "Transfer received"],
        ["Revolut", "2026-09-02", "-50.00", "Transfer to PARTNER PERSON & SAMPLE OWNER"],
        ["Shared", "2026-08-04", "100.00", "Payment from Sample Owner"],
    ]
    assert "counterpart statement may be missing or incomplete" in output


def test_render_report_explains_why_a_transfer_is_unmatched(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    output = _render(statement_folder, make_config(STATEMENT_CONFIG))

    why = {row[3]: row[4] for row in _table_rows(output, "Unmatched transfers")}
    assert why["Transfer received"] == (
        'bbva: transfer from Revolut ("Transfer received") - '
        "no counterpart row found within the window; possible counterparts: Revolut, Shared"
    )
    assert why["Transfer to PARTNER PERSON & SAMPLE OWNER"].endswith(
        " - no counterpart row found within the window; the counterpart may be any own account"
    )


def _unmatched(allowed: frozenset[str] | None) -> ClassifiedRow:
    return ClassifiedRow(
        row=make_row(bank="tbank", account="Black", description="Между своими счетами"),
        kind="own_transfer",
        evidence="tbank: transfer between own tbank accounts",
        allowed=allowed,
    )


def test_unmatched_why_for_any_own_account() -> None:
    assert unmatched_why(_unmatched(None)) == (
        "tbank: transfer between own tbank accounts - "
        "no counterpart row found within the window; the counterpart may be any own account"
    )


def test_unmatched_why_names_every_possible_counterpart() -> None:
    assert unmatched_why(_unmatched(frozenset({"Platinum", "Gold"}))) == (
        "tbank: transfer between own tbank accounts - "
        "no counterpart row found within the window; possible counterparts: Gold, Platinum"
    )


def test_unmatched_why_names_a_single_possible_counterpart() -> None:
    assert unmatched_why(_unmatched(frozenset({"Platinum"}))) == (
        "tbank: transfer between own tbank accounts - "
        "no counterpart row found within the window; possible counterpart: Platinum"
    )


def test_unmatched_why_for_an_empty_allowed_set() -> None:
    assert unmatched_why(_unmatched(frozenset())) == (
        "tbank: transfer between own tbank accounts - "
        "no counterpart row found within the window; "
        "no other account of that bank is configured"
    )


def test_render_report_lists_hidden_pocket_names_by_cause(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config_toml = STATEMENT_CONFIG.replace(
        '[pockets.accounts.Shared]\nTravel = "Travel"',
        '[pockets.accounts.Shared]\nTravel = "hidden"',
    ).replace('[pockets.accounts.Revolut]\n"Flexible Cash Funds" = "Safety"\n', "")
    assert config_toml.count("[pockets.accounts.") == 1

    lines = _render(statement_folder, make_config(config_toml)).splitlines()

    shared = lines.index("revolut_shared.csv: hidden_pocket x5, reverted x1")
    assert lines[shared + 1] == "  pockets mapped to hidden: Travel x5"
    revolut = lines.index("revolut_eur.csv: hidden_pocket x2")
    assert lines[revolut + 1] == "  pockets not in config: Flexible Cash Funds x2"


def _unmatched_bracket_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "2026_09"
    folder.mkdir()
    (folder / "revolut_eur.csv").write_text(
        "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
        "Transfer,Current,2026-09-02 10:00:00,2026-09-02 10:00:00,"
        "Transfer to Sample Owner [Mom],-50.00,0.00,EUR,COMPLETED,50.00\n"
    )
    return folder


REVOLUT_EUR_CONFIG = '[[accounts]]\nbank = "revolut"\nmoneywiz = "Revolut"\nfile = "revolut_eur*"\n'


def test_render_report_survives_brackets_in_an_unmatched_description(
    tmp_path: Path, make_config: Callable[[str], Config]
) -> None:
    folder = _unmatched_bracket_folder(tmp_path)

    output = _render(folder, make_config(REVOLUT_EUR_CONFIG))

    (row,) = _table_rows(output, "Unmatched transfers")
    assert row[3] == "Transfer to Sample Owner [Mom]"
    assert "[Mom]" in row[4]


def test_render_report_shows_the_merged_count_of_every_statement(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    output = _render(statement_folder, make_config(STATEMENT_CONFIG))

    rows = _table_rows(output, "Statements")
    assert [row[0] for row in rows] == [
        "bbva.xlsx",
        "revolut_eur.csv",
        "revolut_saves.csv",
        "revolut_shared.csv",
        "santander.xlsx",
        "tbank_two_accounts.ofx",
        "tbank_two_accounts.ofx",
        "wise.csv",
    ]
    assert [row[5] for row in rows] == ["0", "2", "2", "2", "0", "0", "0", "1"]


def test_render_report_prints_one_line_per_transfer(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    output = _render(statement_folder, make_config(STATEMENT_CONFIG))

    rows = _table_rows(output, "Transfers")
    assert [row[:5] for row in rows] == [
        ["2026-08-01", "Shared", "Travel", "0.50", "lump of 1"],
        ["2026-08-06", "Travel", "Shared", "5.00", "1"],
        ["2026-08-25", "Revolut", "Wise", "44.00", "2"],
        ["2026-08-26", "Revolut", "Safety", "0.40", "lump of 1"],
        ["2026-08-27", "Revolut", "Safety", "200.00", "1"],
        ["2026-09-22", "Wise", "Revolut", "42.00", "2"],
        ["2026-09-24", "Platinum", "Black", "436", "1"],
    ]
    notes = [row[5] for row in rows]
    assert "paired 01:04:20 apart" in notes
    assert "single leg: only possible counterpart" in notes
    assert "pocket move" in notes


def test_render_report_prints_link_notes_under_the_transfers(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    output = _render(statement_folder, make_config(STATEMENT_CONFIG))

    lines = output.splitlines()
    note = next(i for i, line in enumerate(lines) if "counterpart not found in Black" in line)
    transfers = next(i for i, line in enumerate(lines) if line.strip() == "Transfers")
    lumps = next(i for i, line in enumerate(lines) if line.strip() == "Lumps")
    assert transfers < note < lumps


def test_render_report_lists_every_lump(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    output = _render(statement_folder, make_config(STATEMENT_CONFIG))

    rows = _table_rows(output, "Lumps")
    assert rows == [
        ["roundups", "Revolut", "-0.40", "1", "2026-08-26 to 2026-08-26"],
        ["fee", "Safety", "-0.01", "1", "2026-09-27 to 2026-09-27"],
        ["interest", "Safety", "0.13", "1", "2026-09-27 to 2026-09-27"],
        ["roundups", "Shared", "-0.50", "1", "2026-08-01 to 2026-08-01"],
        ["interest", "Travel", "0.01", "1", "2026-08-05 to 2026-08-05"],
    ]


def test_render_report_singularises_the_closing_counts(
    tmp_path: Path, make_config: Callable[[str], Config]
) -> None:
    folder = _unmatched_bracket_folder(tmp_path)

    output = _render(folder, make_config(REVOLUT_EUR_CONFIG))

    assert output.strip().splitlines()[-1] == (
        "1 row ready; nothing written (dry run); 0 lumps, 0 transfers, 1 unmatched"
    )


def _render_result(result: ConvertResult) -> str:
    console = Console(record=True, width=300)
    render_report(result, console)
    return console.export_text()


def test_render_report_warns_when_moneywiz_was_not_read(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    output = _render(statement_folder, make_config(STATEMENT_CONFIG))

    first = output.splitlines()[0]
    assert "lumps may repeat earlier ones" in first
    assert "account names were not checked" in first


def test_render_report_has_no_moneywiz_warning_with_a_snapshot(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)
    plain = run_convert(statement_folder, config, dry_run=True)
    result = run_convert(
        statement_folder, config, dry_run=True, snapshot=snapshot_of(exported_names(plain))
    )

    output = _render_result(result)

    assert "lumps may repeat" not in output
    assert "not checked" not in output


def test_render_report_shows_the_count_covered_by_an_earlier_lump(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)
    plain = run_convert(statement_folder, config, dry_run=True)
    notes = [row.memo for row in plain.export_rows if "smt-lump:" in row.memo]
    result = run_convert(
        statement_folder,
        config,
        dry_run=True,
        snapshot=snapshot_of(exported_names(plain), notes),
    )

    output = _render_result(result)

    assert "Covered by an earlier lump" in output
    covered = {row[2]: row[6] for row in _table_rows(output, "Statements")}
    assert covered == {
        "Shared": "2",
        "Revolut": "1",
        "Safety": "2",
        "Wise": "0",
        "Black": "0",
        "Platinum": "0",
        "BBVA": "0",
        "Santander": "0",
    }


def test_render_report_hides_the_covered_column_when_nothing_is_covered(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    output = _render(statement_folder, make_config(STATEMENT_CONFIG))

    assert "Covered by an earlier lump" not in output


def _cross_currency_transfer() -> Transfer:
    sent = ClassifiedRow(
        row=make_row(
            bank="wise",
            account="Wise",
            amount=Decimal("-50.00"),
            currency="EUR",
            date=datetime(2026, 9, 3, 10, 0, 0),
        ),
        kind="own_transfer",
        evidence="test",
    )
    received = ClassifiedRow(
        row=make_row(
            bank="tbank",
            account="Black",
            amount=Decimal("4500.00"),
            currency="RUB",
            date=datetime(2026, 9, 3, 10, 5, 0),
        ),
        kind="own_transfer",
        evidence="test",
    )
    return Transfer(
        outgoing=sent, incoming=received, source="Wise", destination="Black", note="paired"
    )


def test_render_report_lists_cross_currency_transfers_with_the_received_amount(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    result = run_convert(statement_folder, make_config(STATEMENT_CONFIG), dry_run=True)
    result = replace(result, transfers=(*result.transfers, _cross_currency_transfer()))

    output = _render_result(result)

    (row,) = _table_rows(output, "Cross-currency transfers")
    assert row == ["2026-09-03", "Wise", "Black", "50.00 EUR", "4500.00 RUB"]
    assert "set the received amount by hand" in output


def test_render_report_has_no_cross_currency_section_without_such_transfers(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    output = _render(statement_folder, make_config(STATEMENT_CONFIG))

    assert "Cross-currency" not in output
