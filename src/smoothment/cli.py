from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from smoothment import __version__
from smoothment.config import ConfigError, default_config_path, load_config
from smoothment.convert import ConvertResult, run_convert
from smoothment.moneywiz.locate import MoneyWizRunningError, open_snapshot
from smoothment.moneywiz.model import MoneyWizSnapshot
from smoothment.moneywiz.reader import MoneyWizStoreError
from smoothment.probe.check import ProbeIncompleteError, check_probe, write_probe_results
from smoothment.probe.fixture import probe_instructions, write_probe_csv
from smoothment.report import render_report, render_verify_report
from smoothment.statement.discover import DiscoveryError
from smoothment.statement.model import StatementFormatError
from smoothment.verify import run_verify

app = typer.Typer(no_args_is_help=True, help="Bank statements to MoneyWiz CSV.")
probe_app = typer.Typer(no_args_is_help=True, help="One-time MoneyWiz import experiment.")
app.add_typer(probe_app, name="probe")
console = Console()
err_console = Console(stderr=True)

ConfigOption = typer.Option(
    None, "--config", help="Path to smoothment.toml (default: next to the statement folder)"
)
ProbeConfigOption = typer.Option(
    None, "--config", help="Path to smoothment.toml (default: in the current directory)"
)
AllowRunningOption = typer.Option(False, "--allow-running", help="Read even if MoneyWiz is open")
OutOption = typer.Option(None, "--out", help="Directory for the probe CSV (default: config dir)")
CategoryOption = typer.Option(None, "--category", help="Existing MoneyWiz expense category path")
FolderArgument = typer.Argument(
    ...,
    exists=True,
    file_okay=False,
    resolve_path=True,
    help="Folder of downloaded bank statement files",
)
OutputOption = typer.Option(
    None, "--output", help="Output CSV path (default: <folder>/moneywiz_import.csv)"
)
DryRunOption = typer.Option(False, "--dry-run", help="Report without writing the output CSV")
AllowBalanceMismatchOption = typer.Option(
    False, "--allow-balance-mismatch", help="Write even when a statement's running balance breaks"
)
NoMoneyWizOption = typer.Option(
    False,
    "--no-moneywiz",
    help="Skip the MoneyWiz store: lumps may repeat, account names go unchecked",
)

KNOWN_ERRORS = (
    ConfigError,
    MoneyWizRunningError,
    MoneyWizStoreError,
    ProbeIncompleteError,
    DiscoveryError,
    StatementFormatError,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"smoothment {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True),
) -> None:
    """Smoothment command line."""


def _fail(exc: Exception) -> NoReturn:
    err_console.print(f"[red]error:[/red] {escape(str(exc))}")
    raise typer.Exit(code=2)


def _first_expense_leaf(snapshot: MoneyWizSnapshot) -> str | None:
    parents = {c.path.rsplit(" > ", 1)[0] for c in snapshot.categories if " > " in c.path}
    for category in snapshot.categories:
        if category.type == "expense" and category.path not in parents:
            return category.path
    return None


@probe_app.command("write")
def probe_write(
    config: Path | None = ProbeConfigOption,
    out: Path | None = OutOption,
    category: str | None = CategoryOption,
    allow_running: bool = AllowRunningOption,
) -> None:
    """Write the probe CSV and print the manual steps."""
    try:
        cfg = load_config(config or default_config_path())
        if category is None:
            try:
                category = _first_expense_leaf(
                    open_snapshot(cfg.moneywiz, allow_running=allow_running)
                )
            except (MoneyWizStoreError, MoneyWizRunningError) as exc:
                _fail(
                    Exception(
                        f"{exc}\nPass --category with an existing expense category path instead."
                    )
                )
            if category is None:
                _fail(Exception("MoneyWiz has no expense categories; pass --category."))
        target_dir = out or cfg.path.parent
        csv_path = target_dir / "smoothment_probe.csv"
        write_probe_csv(csv_path, category)
        console.print(probe_instructions(csv_path, category))
    except KNOWN_ERRORS as exc:
        _fail(exc)


@probe_app.command("check")
def probe_check(
    config: Path | None = ProbeConfigOption,
    allow_running: bool = AllowRunningOption,
) -> None:
    """Read MoneyWiz after the probe import and record the answers."""
    try:
        cfg = load_config(config or default_config_path())
        result = check_probe(open_snapshot(cfg.moneywiz, allow_running=allow_running))
        table = Table(title="Probe results")
        table.add_column("question")
        table.add_column("answer")
        for key, value in result.to_toml_dict()["moneywiz"].items():
            table.add_row(key, "yes" if value else "no")
        table.add_row(
            "cross_currency_reciprocal_amount",
            str(result.cross_currency_reciprocal_amount)
            if result.cross_currency_reciprocal_amount is not None
            else "none",
        )
        console.print(table)
        for note in result.notes:
            console.print(f"  - {note}")
        written = write_probe_results(result, cfg.path)
        console.print(f"Recorded in {written}")
    except KNOWN_ERRORS as exc:
        _fail(exc)


def _run_convert_or_fail(
    folder: Path,
    config: Path | None,
    output: Path | None,
    dry_run: bool,
    allow_balance_mismatch: bool,
    no_moneywiz: bool,
    allow_running: bool,
) -> ConvertResult:
    try:
        cfg = load_config(config or default_config_path(folder))
        snapshot = None if no_moneywiz else open_snapshot(cfg.moneywiz, allow_running=allow_running)
        return run_convert(
            folder,
            cfg,
            output=output,
            dry_run=dry_run,
            allow_balance_mismatch=allow_balance_mismatch,
            snapshot=snapshot,
        )
    except (*KNOWN_ERRORS, OSError) as exc:
        _fail(exc)


@app.command("convert")
def convert(
    folder: Path = FolderArgument,
    config: Path | None = ConfigOption,
    output: Path | None = OutputOption,
    dry_run: bool = DryRunOption,
    allow_balance_mismatch: bool = AllowBalanceMismatchOption,
    no_moneywiz: bool = NoMoneyWizOption,
    allow_running: bool = AllowRunningOption,
) -> None:
    """Convert a folder of downloaded bank statements into a MoneyWiz import CSV."""
    result = _run_convert_or_fail(
        folder, config, output, dry_run, allow_balance_mismatch, no_moneywiz, allow_running
    )
    render_report(result, console)
    failed = False
    if result.mismatched and not allow_balance_mismatch:
        outcome = "would not be written" if dry_run else "was not written"
        err_console.print(
            f"[red]error:[/red] balance mismatch: the CSV {outcome}; "
            "pass --allow-balance-mismatch to write anyway"
        )
        failed = True
    if result.unbalanced:
        err_console.print(
            "[red]error:[/red] row accounting mismatch: a parser did not account for every "
            "input row; see the report above"
        )
        failed = True
    if failed:
        raise typer.Exit(code=1)


@app.command("verify")
def verify(
    folder: Path = FolderArgument,
    config: Path | None = ConfigOption,
    allow_running: bool = AllowRunningOption,
) -> None:
    """After the import: report what MoneyWiz is missing, has wrong or has extra, and balances."""
    try:
        cfg = load_config(config or default_config_path(folder))
        snapshot = open_snapshot(cfg.moneywiz, allow_running=allow_running)
        result = run_verify(folder, cfg, snapshot)
    except (*KNOWN_ERRORS, OSError) as exc:
        _fail(exc)
    render_verify_report(result, console)
    if not result.clean:
        raise typer.Exit(code=1)
