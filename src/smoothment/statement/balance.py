from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from smoothment.statement.model import ParsedStatement, StatementRow


@dataclass(frozen=True, slots=True)
class BalanceMismatch:
    file: Path
    chain: str
    row: StatementRow
    expected: Decimal
    found: Decimal


def check_balances(statement: ParsedStatement) -> tuple[BalanceMismatch, ...]:
    """Walk each chain in chronological order, reporting the first broken link.

    A chain row without a balance is a programming error, not a data problem:
    it raises ValueError naming the row.
    """
    mismatches: list[BalanceMismatch] = []
    for chain in statement.chains:
        previous_balance: Decimal | None = None
        for index in chain.indexes:
            row = statement.rows[index]
            if row.balance is None:
                raise ValueError(f"row {row.line} in chain {chain.name!r} has no balance")
            if previous_balance is not None:
                expected = previous_balance + row.amount
                if expected != row.balance:
                    mismatches.append(
                        BalanceMismatch(
                            file=statement.file,
                            chain=chain.name,
                            row=row,
                            expected=expected,
                            found=row.balance,
                        )
                    )
                    break
            previous_balance = row.balance
    return tuple(mismatches)
