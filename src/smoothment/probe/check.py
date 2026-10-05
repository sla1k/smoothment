from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import tomli_w

from smoothment.config import PROBE_FILE_NAME
from smoothment.moneywiz.model import MoneyWizSnapshot, Transaction, normalize_text
from smoothment.probe.fixture import (
    MEMO_PREFIX,
    PROBE_ACCOUNT_EUR,
    PROBE_ACCOUNT_EUR_2,
    PROBE_ACCOUNT_RUB,
    PROBE_AMOUNTS,
    PROBE_DATES,
)


class ProbeIncompleteError(Exception):
    """The probe accounts or the imported probe rows are missing."""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    memo_lands_in_notes: bool
    single_leg_creates_reciprocal: bool
    two_legs_link_once: bool
    existing_leg_links: bool
    cross_currency_reciprocal_amount: Decimal | None
    notes: tuple[str, ...]

    def to_toml_dict(self) -> dict[str, dict[str, bool]]:
        return {
            "moneywiz": {
                "memo_lands_in_notes": self.memo_lands_in_notes,
                "single_leg_creates_reciprocal": self.single_leg_creates_reciprocal,
                "two_legs_link_once": self.two_legs_link_once,
                "existing_leg_links": self.existing_leg_links,
            }
        }


def _same_account(a: str, b: str) -> bool:
    return normalize_text(a).casefold() == normalize_text(b).casefold()


def _rows(
    snapshot: MoneyWizSnapshot, account: str, case: str, amount: Decimal
) -> tuple[Transaction, ...]:
    day = PROBE_DATES[case]
    return tuple(t for t in snapshot.transactions_in(account, day, day) if t.amount == amount)


def check_probe(snapshot: MoneyWizSnapshot) -> ProbeResult:
    missing = [
        n
        for n in (PROBE_ACCOUNT_EUR, PROBE_ACCOUNT_EUR_2, PROBE_ACCOUNT_RUB)
        if snapshot.account(n) is None
    ]
    if missing:
        raise ProbeIncompleteError(f"Probe accounts missing in MoneyWiz: {', '.join(missing)}")
    notes: list[str] = []

    plain = _rows(snapshot, PROBE_ACCOUNT_EUR, "plain", PROBE_AMOUNTS["plain"])
    if not plain:
        raise ProbeIncompleteError(
            "The plain probe row (-12.34 on 2026-01-05) is not in MoneyWiz; was the file imported?"
        )
    memo_ok = any(f"{MEMO_PREFIX}plain" in t.notes for t in plain)
    notes.append(f"memo in notes: {'yes' if memo_ok else 'no'} (notes={plain[0].notes!r})")

    single_in = _rows(snapshot, PROBE_ACCOUNT_EUR_2, "single", -PROBE_AMOUNTS["single"])
    single_ok = len(single_in) >= 1
    notes.append(f"single-leg reciprocal in {PROBE_ACCOUNT_EUR_2}: {len(single_in)} row(s)")

    two_out = _rows(snapshot, PROBE_ACCOUNT_EUR, "two", PROBE_AMOUNTS["two"])
    two_in = _rows(snapshot, PROBE_ACCOUNT_EUR_2, "two", -PROBE_AMOUNTS["two"])
    two_total = len(two_out) + len(two_in)
    linked = (
        two_total == 2
        and all(
            t.kind == "transfer_out"
            and t.other_account
            and _same_account(t.other_account, PROBE_ACCOUNT_EUR_2)
            for t in two_out
        )
        and all(
            t.kind == "transfer_in"
            and t.other_account
            and _same_account(t.other_account, PROBE_ACCOUNT_EUR)
            for t in two_in
        )
    )
    if two_total > 2:
        notes.append(f"two-leg import produced {two_total} rows: duplicates")
    else:
        notes.append(f"two-leg import: {two_total} rows, linked={'yes' if linked else 'no'}")

    existing_rows = _rows(snapshot, PROBE_ACCOUNT_EUR_2, "existing", -PROBE_AMOUNTS["existing"])
    existing_ok = (
        len(existing_rows) == 1
        and existing_rows[0].kind == "transfer_in"
        and existing_rows[0].other_account is not None
        and _same_account(existing_rows[0].other_account, PROBE_ACCOUNT_EUR)
    )
    if len(existing_rows) > 1:
        notes.append(
            f"existing-leg case produced {len(existing_rows)} rows"
            f" in {PROBE_ACCOUNT_EUR_2}: duplicate"
        )
    else:
        existing_kind = existing_rows[0].kind if existing_rows else "none"
        notes.append(f"existing-leg case: {len(existing_rows)} row(s), kind={existing_kind}")

    day = PROBE_DATES["xcur"]
    rub_rows = snapshot.transactions_in(PROBE_ACCOUNT_RUB, day, day)
    xcur_amount = rub_rows[0].amount if rub_rows else None
    xcur_display = xcur_amount if xcur_amount is not None else "none"
    notes.append(f"cross-currency reciprocal in {PROBE_ACCOUNT_RUB}: {xcur_display}")

    return ProbeResult(
        memo_lands_in_notes=memo_ok,
        single_leg_creates_reciprocal=single_ok,
        two_legs_link_once=linked,
        existing_leg_links=existing_ok,
        cross_currency_reciprocal_amount=xcur_amount,
        notes=tuple(notes),
    )


def write_probe_results(result: ProbeResult, config_path: Path) -> Path:
    out = config_path.parent / PROBE_FILE_NAME
    out.write_bytes(tomli_w.dumps(result.to_toml_dict()).encode("utf-8"))
    return out
