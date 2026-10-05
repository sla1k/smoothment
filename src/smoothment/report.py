from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from smoothment.classify.model import ClassifiedRow
from smoothment.convert import ConvertResult, FileResult
from smoothment.link import Transfer
from smoothment.lumps import Lump
from smoothment.verify import BalanceEntry, VerifyResult

UNMATCHED_MISSING = "no counterpart row found within the window"


@dataclass(frozen=True, slots=True)
class _TransferLine:
    date: date
    source: str
    destination: str
    amount: Decimal
    legs: str
    note: str


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _balance_cell(file_result: FileResult) -> str:
    if not file_result.statement.chains:
        return "n/a"
    return "mismatch" if file_result.mismatches else "ok"


def _build_table(result: ConvertResult) -> Table:
    table = Table(title="Statements")
    table.add_column("File")
    table.add_column("Format")
    table.add_column("Account")
    table.add_column("Rows", justify="right")
    table.add_column("Exported", justify="right")
    table.add_column("Merged", justify="right")
    show_covered = any(file_result.skipped for file_result in result.files)
    if show_covered:
        table.add_column("Covered by an earlier lump", justify="right")
    table.add_column("Excluded", justify="right")
    table.add_column("Balance")
    for file_result in result.files:
        statement = file_result.statement
        accounting = file_result.accounting
        table.add_row(
            escape(statement.file.name),
            escape(f"{statement.bank}/{statement.kind}"),
            escape(statement.account),
            str(accounting.source_rows),
            str(accounting.exported),
            str(accounting.merged),
            *([str(accounting.skipped)] if show_covered else []),
            str(accounting.excluded),
            _balance_cell(file_result),
        )
    return table


def _transfer_line(transfer: Transfer) -> _TransferLine:
    legs = [leg for leg in (transfer.outgoing, transfer.incoming) if leg is not None]
    primary = legs[0]
    return _TransferLine(
        date=min(leg.row.date for leg in legs).date(),
        source=transfer.source,
        destination=transfer.destination,
        amount=abs(primary.row.amount),
        legs=str(len(legs)),
        note=transfer.note,
    )


def _lump_transfer_line(lump: Lump) -> _TransferLine:
    assert lump.counterpart is not None
    outgoing = lump.amount < 0
    return _TransferLine(
        date=lump.date,
        source=lump.account if outgoing else lump.counterpart,
        destination=lump.counterpart if outgoing else lump.account,
        amount=abs(lump.amount),
        legs=f"lump of {len(lump.rows)}",
        note=f"round-ups, pocket {lump.pocket}" if lump.pocket else "round-ups",
    )


def _transfer_lines(result: ConvertResult) -> list[_TransferLine]:
    lines = [_transfer_line(transfer) for transfer in result.transfers]
    lines.extend(_lump_transfer_line(lump) for lump in result.lumps if lump.kind == "roundups")
    lines.sort(key=lambda line: (line.date, line.source, line.destination))
    return lines


def _print_moneywiz_warning(result: ConvertResult, console: Console) -> None:
    if not result.moneywiz_checked:
        console.print(
            "[yellow]warning: MoneyWiz was not read; lumps may repeat earlier ones and "
            "account names were not checked against MoneyWiz.[/yellow]"
        )


def _possible_counterparts(allowed: frozenset[str] | None) -> str:
    if allowed is None:
        return "the counterpart may be any own account"
    if not allowed:
        return "no other account of that bank is configured"
    noun = "counterpart" if len(allowed) == 1 else "counterparts"
    return f"possible {noun}: {', '.join(sorted(allowed))}"


def unmatched_why(unmatched: ClassifiedRow) -> str:
    return (
        f"{unmatched.evidence} - {UNMATCHED_MISSING}; {_possible_counterparts(unmatched.allowed)}"
    )


def _print_unmatched(result: ConvertResult, console: Console) -> None:
    if not result.unmatched:
        return
    table = Table(title="Unmatched transfers")
    table.add_column("Account")
    table.add_column("Date")
    table.add_column("Amount", justify="right")
    table.add_column("Description")
    table.add_column("Why")
    for unmatched in result.unmatched:
        row = unmatched.row
        table.add_row(
            escape(unmatched.account or row.account),
            f"{row.date:%Y-%m-%d}",
            str(row.amount),
            escape(row.description),
            escape(unmatched_why(unmatched)),
        )
    console.print(table)
    console.print(
        "These rows are exported with the payee 'Unmatched transfer'. "
        "The counterpart statement may be missing or incomplete."
    )


def _print_transfers(result: ConvertResult, console: Console) -> None:
    lines = _transfer_lines(result)
    if lines:
        table = Table(title="Transfers")
        table.add_column("Date")
        table.add_column("From")
        table.add_column("To")
        table.add_column("Amount", justify="right")
        table.add_column("Legs")
        table.add_column("Note")
        for line in lines:
            table.add_row(
                f"{line.date:%Y-%m-%d}",
                escape(line.source),
                escape(line.destination),
                str(line.amount),
                line.legs,
                escape(line.note),
            )
        console.print(table)
    for note in result.link_notes:
        console.print(f"  {escape(note)}")


def _cross_currency(result: ConvertResult) -> list[Transfer]:
    pairs = [
        transfer
        for transfer in result.transfers
        if transfer.outgoing is not None
        and transfer.incoming is not None
        and transfer.outgoing.row.currency != transfer.incoming.row.currency
    ]
    return sorted(pairs, key=lambda t: (_transfer_line(t).date, t.source, t.destination))


def _print_cross_currency(result: ConvertResult, console: Console) -> None:
    pairs = _cross_currency(result)
    if not pairs:
        return
    table = Table(title="Cross-currency transfers")
    table.add_column("Date")
    table.add_column("From")
    table.add_column("To")
    table.add_column("Sent", justify="right")
    table.add_column("Received", justify="right")
    for transfer in pairs:
        assert transfer.outgoing is not None and transfer.incoming is not None
        sent, received = transfer.outgoing.row, transfer.incoming.row
        table.add_row(
            f"{_transfer_line(transfer).date:%Y-%m-%d}",
            escape(transfer.source),
            escape(transfer.destination),
            f"{abs(sent.amount)} {escape(sent.currency)}",
            f"{abs(received.amount)} {escape(received.currency)}",
        )
    console.print(table)
    console.print(
        "After the import, set the received amount by hand on the incoming side of each "
        "of these in MoneyWiz."
    )


def _print_lumps(result: ConvertResult, console: Console) -> None:
    if not result.lumps:
        return
    table = Table(title="Lumps")
    table.add_column("Kind")
    table.add_column("Account")
    table.add_column("Amount", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Dates")
    for lump in result.lumps:
        table.add_row(
            lump.kind,
            escape(lump.account),
            str(lump.amount),
            str(len(lump.rows)),
            f"{lump.first:%Y-%m-%d} to {lump.date:%Y-%m-%d}",
        )
    console.print(table)


def _print_reasons(result: ConvertResult, console: Console) -> None:
    for file_result in result.files:
        reasons = file_result.reasons
        if not reasons:
            continue
        parts = ", ".join(f"{escape(reason)} x{count}" for reason, count in sorted(reasons.items()))
        console.print(f"{escape(file_result.statement.file.name)}: {parts}")
        for detail, pockets in _hidden_pockets(file_result):
            names = ", ".join(f"{escape(pocket)} x{count}" for pocket, count in pockets)
            console.print(f"  pockets {escape(detail)}: {names}")


def _hidden_pockets(file_result: FileResult) -> list[tuple[str, list[tuple[str, int]]]]:
    counts: dict[str, dict[str, int]] = {}
    for excluded in file_result.excluded:
        detail = excluded.detail
        if excluded.reason != "hidden_pocket" or excluded.row.pocket is None or detail is None:
            continue
        by_pocket = counts.setdefault(detail, {})
        by_pocket[excluded.row.pocket] = by_pocket.get(excluded.row.pocket, 0) + 1
    return [(detail, sorted(counts[detail].items())) for detail in sorted(counts)]


def _print_discovery_notes(result: ConvertResult, console: Console) -> None:
    for skipped in result.discovery.skipped:
        console.print(f"skipped {escape(skipped.path.name)}: {escape(skipped.reason)}")
    for unrecognized in result.discovery.unrecognized:
        console.print(
            f"[yellow]unrecognized {escape(unrecognized.path.name)}: "
            f"{escape(unrecognized.reason)}[/yellow]"
        )


def _print_mismatches(result: ConvertResult, console: Console) -> None:
    for file_result in result.files:
        if not file_result.mismatches:
            continue
        pending_rows = [row for row in file_result.statement.rows if row.state == "pending"]
        for mismatch in file_result.mismatches:
            row = mismatch.row
            description = escape(row.description[:40])
            console.print(
                f"balance mismatch in {escape(mismatch.file.name)} "
                f"(chain {escape(mismatch.chain)}): "
                f"row {row.line} {row.date:%Y-%m-%d} '{description}' - "
                f"expected {mismatch.expected}, found {mismatch.found}"
            )
            if pending_rows:
                console.print("  pending rows in this file (likely explanation):")
                for pending in pending_rows:
                    console.print(
                        f"    row {pending.line} {pending.date:%Y-%m-%d} "
                        f"{pending.amount} '{escape(pending.description)}'"
                    )


def _print_accounting(result: ConvertResult, console: Console) -> None:
    for file_result in result.unbalanced:
        accounting = file_result.accounting
        console.print(
            f"[red]row accounting mismatch[/red]: {escape(file_result.statement.file.name)}: "
            f"{accounting.source_rows} input rows, {accounting.accounted} accounted"
        )


def _print_summary(result: ConvertResult, console: Console) -> None:
    rows = _count(len(result.export_rows), "row")
    if result.written:
        summary = f"wrote {rows} to {escape(str(result.output))}"
    elif result.dry_run:
        summary = f"{rows} ready; nothing written (dry run)"
    else:
        summary = f"{rows} ready; nothing written"
    summary += (
        f"; {_count(len(result.lumps), 'lump')}, "
        f"{_count(len(_transfer_lines(result)), 'transfer')}, {len(result.unmatched)} unmatched"
    )
    unrecognized = len(result.discovery.unrecognized)
    if unrecognized:
        summary += f"; [yellow]{unrecognized} unrecognized file(s)[/yellow]"
    console.print(summary)


def render_report(result: ConvertResult, console: Console) -> None:
    _print_moneywiz_warning(result, console)
    _print_unmatched(result, console)
    console.print(_build_table(result))
    _print_reasons(result, console)
    _print_accounting(result, console)
    _print_discovery_notes(result, console)
    _print_mismatches(result, console)
    _print_transfers(result, console)
    _print_cross_currency(result, console)
    _print_lumps(result, console)
    _print_summary(result, console)


def _verify_table(title: str, *columns: str) -> Table:
    table = Table(title=title)
    for column in columns:
        right = column in ("Amount", "Statement", "MoneyWiz", "Difference")
        table.add_column(column, justify="right" if right else "left")
    return table


def _print_missing(result: VerifyResult, console: Console) -> None:
    if not result.missing:
        return
    table = _verify_table("Missing in MoneyWiz", "Date", "Account", "Amount", "Description")
    for item in result.missing:
        table.add_row(
            f"{item.day:%Y-%m-%d}",
            escape(item.account),
            str(item.amount),
            escape(item.description),
        )
    console.print(table)
    console.print("These statement rows are not in MoneyWiz: import them or enter them by hand.")


def _print_wrong(result: VerifyResult, console: Console) -> None:
    if not result.wrong:
        return
    table = _verify_table("Wrong in MoneyWiz", "Date", "Account", "Amount", "Description", "Fix")
    for item in result.wrong:
        table.add_row(
            f"{item.day:%Y-%m-%d}",
            escape(item.account),
            str(item.amount),
            escape(item.description),
            escape(item.problem),
        )
    console.print(table)


def _print_extra(result: VerifyResult, console: Console) -> None:
    if not result.extra:
        return
    table = _verify_table("Extra in MoneyWiz", "Date", "Account", "Amount", "Description")
    for item in result.extra:
        table.add_row(
            f"{item.day:%Y-%m-%d}",
            escape(item.account),
            str(item.amount),
            escape(item.description),
        )
    console.print(table)
    console.print(
        "No statement row matches these MoneyWiz rows (hand-entered rows, duplicates or "
        "rows from other statements)."
    )


def _balance_status(entry: BalanceEntry) -> str:
    if entry.difference == 0:
        return "ok"
    if entry.unexplained is None:
        return ""
    if entry.pending_explains:
        return "explained by pending rows"
    return "explained" if entry.unexplained == 0 else f"unexplained {entry.unexplained}"


def _balance_cells(entry: BalanceEntry) -> list[str]:
    if entry.note is not None:
        return [escape(entry.account), "", "", "", "", "", "", "", escape(entry.note)]
    difference = entry.difference
    return [
        escape(entry.account),
        f"{entry.day:%Y-%m-%d}" if entry.day is not None else "",
        str(entry.statement),
        "unknown account" if entry.moneywiz is None else str(entry.moneywiz),
        "" if difference is None else str(difference),
        str(entry.pending),
        str(entry.missing),
        str(entry.extra),
        _balance_status(entry),
    ]


def _print_balances(result: VerifyResult, console: Console) -> None:
    if not result.balances:
        return
    table = _verify_table(
        "Balances",
        "Account",
        "Date",
        "Statement",
        "MoneyWiz",
        "Difference",
        "Pending",
        "Missing",
        "Extra",
        "Status",
    )
    for entry in result.balances:
        table.add_row(*_balance_cells(entry))
    console.print(table)
    console.print(
        "Difference is MoneyWiz minus the statement. Pending, Missing and Extra are the "
        "amounts that explain it (pending + extra - missing)."
    )


def _print_inconsistent(result: VerifyResult, console: Console) -> None:
    if not result.inconsistent:
        return
    console.print(
        "[yellow]warning: these statements do not add up on their own, so the comparison "
        "below may be wrong; `smoothment convert --dry-run` shows the details:[/yellow]"
    )
    for item in result.inconsistent:
        console.print(f"  {escape(item.file.name)}: {escape(item.problem)}")


def render_verify_report(result: VerifyResult, console: Console) -> None:
    _print_inconsistent(result, console)
    _print_missing(result, console)
    _print_wrong(result, console)
    _print_extra(result, console)
    _print_balances(result, console)
    if result.clean:
        console.print("Nothing to fix: every statement row is in MoneyWiz and the balances agree.")
        return
    summary = (
        f"{len(result.missing)} missing, {len(result.wrong)} wrong, {len(result.extra)} extra, "
        f"{_count(len(result.disagreeing), 'balance')} off"
    )
    if result.inconsistent:
        summary += f", {_count(len(result.inconsistent), 'statement problem')}"
    console.print(summary + ".")
