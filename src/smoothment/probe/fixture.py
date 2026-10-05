import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

PROBE_ACCOUNT_EUR = "SMT Probe EUR"
PROBE_ACCOUNT_EUR_2 = "SMT Probe EUR 2"
PROBE_ACCOUNT_RUB = "SMT Probe RUB"
PROBE_PAYEE = "SMT Probe Shop"
MEMO_PREFIX = "smt:probe:"
COLUMNS = ("Date", "Amount", "Payee", "Description", "Category", "Account", "Transfers", "Memo")

PROBE_DATES: dict[str, date] = {
    "plain": date(2026, 1, 5),
    "single": date(2026, 1, 6),
    "two": date(2026, 1, 7),
    "xcur": date(2026, 1, 8),
    "existing": date(2026, 1, 9),
}
PROBE_AMOUNTS: dict[str, Decimal] = {
    "plain": Decimal("-12.34"),
    "single": Decimal("-20.00"),
    "two": Decimal("-30.00"),
    "xcur": Decimal("-40.00"),
    "existing": Decimal("-33.00"),
}


@dataclass(frozen=True, slots=True)
class ProbeRow:
    date: date
    amount: Decimal
    payee: str
    description: str
    category: str
    account: str
    transfers: str
    memo: str


def probe_rows(category: str) -> tuple[ProbeRow, ...]:
    d, a = PROBE_DATES, PROBE_AMOUNTS
    return (
        ProbeRow(
            d["plain"],
            a["plain"],
            PROBE_PAYEE,
            "probe plain",
            category,
            PROBE_ACCOUNT_EUR,
            "",
            f"{MEMO_PREFIX}plain",
        ),
        ProbeRow(
            d["single"],
            a["single"],
            "",
            "probe single leg",
            "",
            PROBE_ACCOUNT_EUR,
            PROBE_ACCOUNT_EUR_2,
            f"{MEMO_PREFIX}single",
        ),
        ProbeRow(
            d["two"],
            a["two"],
            "",
            "probe two legs out",
            "",
            PROBE_ACCOUNT_EUR,
            PROBE_ACCOUNT_EUR_2,
            f"{MEMO_PREFIX}two-out",
        ),
        ProbeRow(
            d["two"],
            -a["two"],
            "",
            "probe two legs in",
            "",
            PROBE_ACCOUNT_EUR_2,
            PROBE_ACCOUNT_EUR,
            f"{MEMO_PREFIX}two-in",
        ),
        ProbeRow(
            d["xcur"],
            a["xcur"],
            "",
            "probe cross currency",
            "",
            PROBE_ACCOUNT_EUR,
            PROBE_ACCOUNT_RUB,
            f"{MEMO_PREFIX}xcur",
        ),
        ProbeRow(
            d["existing"],
            a["existing"],
            "",
            "probe existing leg",
            "",
            PROBE_ACCOUNT_EUR,
            PROBE_ACCOUNT_EUR_2,
            f"{MEMO_PREFIX}existing",
        ),
    )


def write_probe_csv(path: Path, category: str) -> tuple[ProbeRow, ...]:
    rows = probe_rows(category)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(COLUMNS)
        for r in rows:
            writer.writerow(
                (
                    r.date.isoformat(),
                    f"{r.amount:.2f}",
                    r.payee,
                    r.description,
                    r.category,
                    r.account,
                    r.transfers,
                    r.memo,
                )
            )
    return rows


def probe_instructions(csv_path: Path, category: str) -> str:
    existing_amount = -PROBE_AMOUNTS["existing"]
    instructions = (
        f"Probe file written: {csv_path}\n"
        "\n"
        "Do this in MoneyWiz, in order:\n"
        f' 1. Create three empty accounts: "{PROBE_ACCOUNT_EUR}" (EUR), '
        f'"{PROBE_ACCOUNT_EUR_2}" (EUR), "{PROBE_ACCOUNT_RUB}" (RUB).\n'
        f' 2. In "{PROBE_ACCOUNT_EUR_2}" add ONE income by hand: '
        f"{existing_amount:.2f} EUR dated {PROBE_DATES['existing'].isoformat()}, "
        'description "probe existing leg".\n'
        f" 3. Import {csv_path.name} (File > Import). In the wizard map the columns "
        "by their header names,\n"
        "    set the date format to yyyy-MM-dd, map Account to the account column "
        "and Transfers to the transfers column.\n"
        f'    The category "{category}" must already exist.\n'
        " 4. Quit MoneyWiz.\n"
        " 5. Run: smoothment probe check\n"
        "\n"
        "The check reads the store and records the answers in smoothment.probe.toml "
        "next to your config.\n"
        "Delete the three probe accounts afterwards."
    )
    return instructions
