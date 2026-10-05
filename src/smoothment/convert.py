from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from smoothment.classify import classify_statement
from smoothment.classify.model import ClassifiedRow, ClassifyContext
from smoothment.classify.owner import OwnerMatcher
from smoothment.config import Config, ConfigError
from smoothment.export import (
    OUTPUT_NAME,
    ExportPlan,
    ExportRow,
    TransferLeg,
    assign_tags,
    memo_tag,
    to_export_rows,
    write_csv,
)
from smoothment.link import Transfer, link
from smoothment.lumps import Lump, build_lumps
from smoothment.moneywiz.model import MoneyWizSnapshot
from smoothment.reconcile import lump_cutoffs
from smoothment.statement.balance import BalanceMismatch, check_balances
from smoothment.statement.discover import Discovery, discover
from smoothment.statement.model import ParsedStatement, StatementRow
from smoothment.statement.parsers import PARSERS

DUPLICATE_OF_OTHER_FILE = "duplicate_of_other_file"
# MoneyWiz drops rows with a zero amount on import (seen 2026-10-04: bonus-point cashback rows).
ZERO_AMOUNT = "zero_amount"


@dataclass(frozen=True, slots=True)
class ExcludedRow:
    row: StatementRow
    reason: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RowAccounting:
    source_rows: int
    exported: int
    merged: int
    skipped: int
    excluded: int

    @property
    def accounted(self) -> int:
        return self.exported + self.merged + self.skipped + self.excluded

    @property
    def balanced(self) -> bool:
        return self.source_rows == self.accounted


@dataclass(frozen=True, slots=True)
class FileResult:
    statement: ParsedStatement
    classified: tuple[ClassifiedRow, ...]
    exported: tuple[ClassifiedRow, ...]
    merged: tuple[ClassifiedRow, ...]
    skipped: tuple[ClassifiedRow, ...]
    excluded: tuple[ExcludedRow, ...]
    mismatches: tuple[BalanceMismatch, ...]

    @property
    def accounting(self) -> RowAccounting:
        return RowAccounting(
            source_rows=self.statement.input_rows,
            exported=len(self.exported),
            merged=len(self.merged),
            skipped=len(self.skipped),
            excluded=len(self.excluded) + len(self.statement.skipped),
        )

    @property
    def reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for excluded in self.excluded:
            counts[excluded.reason] = counts.get(excluded.reason, 0) + 1
        for skipped in self.statement.skipped:
            counts[skipped.reason] = counts.get(skipped.reason, 0) + 1
        return counts


@dataclass(frozen=True, slots=True)
class ConvertResult:
    discovery: Discovery
    files: tuple[FileResult, ...]
    export_rows: tuple[ExportRow, ...]
    output: Path
    dry_run: bool
    written: bool
    transfers: tuple[Transfer, ...]
    unmatched: tuple[ClassifiedRow, ...]
    lumps: tuple[Lump, ...]
    link_notes: tuple[str, ...]
    moneywiz_checked: bool
    tags: Mapping[int, str] = field(default_factory=dict)  # id(StatementRow) -> memo tag

    @property
    def mismatched(self) -> bool:
        return any(result.mismatches for result in self.files)

    @property
    def unbalanced(self) -> tuple[FileResult, ...]:
        return tuple(result for result in self.files if not result.accounting.balanced)


def _check_accounts(export_rows: tuple[ExportRow, ...], snapshot: MoneyWizSnapshot) -> None:
    names = {name for row in export_rows for name in (row.account, row.transfers) if name}
    missing = sorted(name for name in names if snapshot.account(name) is None)
    if missing:
        listed = ", ".join(repr(name) for name in missing)
        raise ConfigError(
            f"MoneyWiz has no account named {listed}; importing the CSV would create "
            "them as new accounts. Fix the names in the config or create the accounts first."
        )


def _split_transfer(transfer: Transfer) -> tuple[TransferLeg, ClassifiedRow | None]:
    """The leg a transfer exports, and the other leg merged into it."""
    if transfer.outgoing is not None:
        leg = TransferLeg(
            row=transfer.outgoing, counterpart=transfer.destination, merged=transfer.incoming
        )
        return leg, transfer.incoming
    assert transfer.incoming is not None
    return TransferLeg(row=transfer.incoming, counterpart=transfer.source), None


@dataclass(frozen=True, slots=True)
class _Classified:
    statement: ParsedStatement
    classified: tuple[ClassifiedRow, ...]
    excluded: tuple[ExcludedRow, ...]
    lumps: tuple[Lump, ...]
    remaining: tuple[ClassifiedRow, ...]
    covered: tuple[ClassifiedRow, ...]


def _drop_duplicates(
    statement: ParsedStatement, earlier_tags: set[str]
) -> tuple[tuple[StatementRow, ...], tuple[ExcludedRow, ...]]:
    """Exclude rows an earlier file already holds; identical rows within one file stay."""
    kept: list[StatementRow] = []
    excluded: list[ExcludedRow] = []
    for row in statement.rows:
        if memo_tag(row) in earlier_tags:
            excluded.append(ExcludedRow(row=row, reason=DUPLICATE_OF_OTHER_FILE))
        else:
            kept.append(row)
    return tuple(kept), tuple(excluded)


def _classify(
    statement: ParsedStatement,
    kept: tuple[StatementRow, ...],
    duplicates: tuple[ExcludedRow, ...],
    context: ClassifyContext,
    covered: Mapping[str, datetime] | None,
) -> _Classified:
    classified = classify_statement(replace(statement, rows=kept), context)
    excluded = list(duplicates)
    included: list[ClassifiedRow] = []
    for row in classified:
        if row.kind == "excluded":
            assert row.reason is not None
            excluded.append(ExcludedRow(row=row.row, reason=row.reason, detail=row.reason_detail))
        elif row.row.amount == 0:
            excluded.append(ExcludedRow(row=row.row, reason=ZERO_AMOUNT))
        else:
            included.append(row)
    lumps, remaining, covered_rows = build_lumps(included, context.config, covered)
    return _Classified(
        statement=statement,
        classified=classified,
        excluded=tuple(excluded),
        lumps=lumps,
        remaining=remaining,
        covered=covered_rows,
    )


def run_convert(
    folder: Path,
    config: Config,
    *,
    output: Path | None = None,
    dry_run: bool = False,
    allow_balance_mismatch: bool = False,
    snapshot: MoneyWizSnapshot | None = None,
    check_accounts: bool = True,
) -> ConvertResult:
    discovery = discover(folder, config)
    context = ClassifyContext(config=config, owner=OwnerMatcher(config.owner))
    covered = lump_cutoffs(snapshot) if snapshot is not None else None

    statements: list[_Classified] = []
    tags: dict[int, str] = {}
    earlier_tags: set[str] = set()
    for discovered in discovery.files:
        parser = PARSERS[(discovered.bank, discovered.kind)]
        statement = parser(discovered.path, discovered.account, discovered.identity)
        kept, duplicates = _drop_duplicates(statement, earlier_tags)
        earlier_tags |= {memo_tag(row) for row in kept}
        tags.update(assign_tags(kept))
        statements.append(_classify(statement, kept, duplicates, context, covered))

    linked = link([row for s in statements for row in s.remaining], config.transfers)
    transfer_exports: list[TransferLeg] = []
    merged_legs: set[int] = set()
    for transfer in linked.transfers:
        leg, merged = _split_transfer(transfer)
        transfer_exports.append(leg)
        if merged is not None:
            merged_legs.add(id(merged))
    not_plain = {id(leg.row) for leg in transfer_exports} | merged_legs
    not_plain |= {id(row) for row in linked.unmatched}

    file_results: list[FileResult] = []
    plain: list[ClassifiedRow] = []
    for s in statements:
        merged_here = {id(row) for lump in s.lumps for row in lump.rows} | merged_legs
        plain.extend(row for row in s.remaining if id(row) not in not_plain)
        file_results.append(
            FileResult(
                statement=s.statement,
                classified=s.classified,
                exported=tuple(row for row in s.remaining if id(row) not in merged_legs),
                merged=tuple(row for row in s.classified if id(row) in merged_here),
                skipped=s.covered,
                excluded=s.excluded,
                mismatches=check_balances(s.statement),
            )
        )

    lumps = tuple(lump for s in statements for lump in s.lumps)
    plan = ExportPlan(
        plain=tuple(plain),
        transfers=tuple(transfer_exports),
        unmatched=linked.unmatched,
        lumps=lumps,
        tags=tags,
    )
    export_rows = to_export_rows(plan)
    if snapshot is not None and check_accounts:
        _check_accounts(export_rows, snapshot)
    target = output or folder / OUTPUT_NAME
    mismatched = any(result.mismatches for result in file_results)
    written = not dry_run and (allow_balance_mismatch or not mismatched)
    if written:
        write_csv(target, export_rows)

    return ConvertResult(
        discovery=discovery,
        files=tuple(file_results),
        export_rows=export_rows,
        output=target,
        dry_run=dry_run,
        written=written,
        transfers=linked.transfers,
        unmatched=linked.unmatched,
        lumps=lumps,
        link_notes=linked.notes,
        moneywiz_checked=snapshot is not None,
        tags=tags,
    )
