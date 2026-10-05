import csv
import fnmatch
import zipfile
from dataclasses import dataclass
from pathlib import Path

import xlrd
from openpyxl.utils.exceptions import InvalidFileException

from smoothment.config import AccountEntry, AccountKind, Config
from smoothment.export import COLUMNS
from smoothment.statement.parsers import bbva, revolut, santander, sovcombank, tbank, wise
from smoothment.statement.sheets import xls_rows, xlsx_rows

STATEMENT_SUFFIXES = {".csv", ".ofx", ".xlsx", ".xls"}

_OFX_SNIFF_CHARS = 4000


class DiscoveryError(Exception):
    """A statement file's bank/account could not be determined unambiguously."""


@dataclass(frozen=True, slots=True)
class Passed:
    """A file was sniffed but is not itself something to convert."""

    reason: str
    recognized: bool


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    path: Path
    bank: str
    kind: AccountKind
    identity: str | None
    account: str
    evidence: str


@dataclass(frozen=True, slots=True)
class PassedFile:
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class Discovery:
    files: tuple[DiscoveredFile, ...]
    skipped: tuple[PassedFile, ...]
    unrecognized: tuple[PassedFile, ...]


def _sniff_csv(path: Path) -> tuple[str, AccountKind] | Passed:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh), [])
    except OSError, UnicodeDecodeError:
        return Passed("unreadable CSV file", recognized=False)
    if header[: len(revolut.CURRENT_SNIFF_PREFIX)] == revolut.CURRENT_SNIFF_PREFIX:
        return ("revolut", "current")
    if header == revolut.POCKET_EXPORT_HEADER:
        return Passed(
            "Revolut pocket export; its rows are already in the main Revolut export",
            recognized=True,
        )
    if (
        len(header) >= 3
        and header[:2] == revolut.SAVINGS_HEADER_PREFIX
        and header[2].startswith(revolut.SAVINGS_VALUE_PREFIX)
    ):
        return ("revolut", "savings")
    if header and header[0] == wise.FIRST_COLUMN:
        return ("wise", "current")
    if header == COLUMNS:
        return Passed("smoothment output", recognized=True)
    return Passed(f"unrecognized CSV header: {header[:4]}", recognized=False)


def _sniff_ofx(path: Path) -> tuple[str, AccountKind] | Passed:
    with path.open(encoding="utf-8", errors="replace") as fh:
        head = fh.read(_OFX_SNIFF_CHARS)
    if "<OFX>" in head and f"<BANKID>{tbank.BANK_ID}</BANKID>" in head:
        return ("tbank", "current")
    return Passed("OFX file that is not a TBank export", recognized=False)


def _sniff_xlsx(path: Path) -> tuple[str, AccountKind] | Passed:
    try:
        sheet = xlsx_rows(path)
    except InvalidFileException, zipfile.BadZipFile, KeyError, OSError:
        return Passed("unreadable XLSX file", recognized=False)
    for row in sheet[: santander.TITLE_ROWS]:
        for cell in row:
            if isinstance(cell, str) and cell == santander.TITLE:
                return ("santander", "current")
    header = bbva.header_of(sheet)
    if header in (bbva.ENGLISH, bbva.SPANISH):
        return ("bbva", "current")
    return Passed("unrecognized XLSX content", recognized=False)


def _sniff_xls(path: Path) -> tuple[str, AccountKind] | Passed:
    try:
        rows = xls_rows(path)
    except xlrd.XLRDError, OSError:
        return Passed("unreadable XLS file", recognized=False)
    if rows and [cell.strip() for cell in rows[0]] == sovcombank.HEADER:
        return ("sovcombank", "current")
    return Passed("unrecognized XLS content", recognized=False)


def sniff(path: Path) -> tuple[str, AccountKind] | Passed:
    suffix = path.suffix.casefold()
    if suffix == ".csv":
        return _sniff_csv(path)
    if suffix == ".ofx":
        return _sniff_ofx(path)
    if suffix == ".xlsx":
        return _sniff_xlsx(path)
    if suffix == ".xls":
        return _sniff_xls(path)
    raise ValueError(f"not a statement suffix: {path.name}")


def file_identities(path: Path, bank: str) -> tuple[str | None, ...]:
    if bank == "tbank":
        ids = tbank.account_ids(path)
        if not ids:
            raise DiscoveryError(f"{path.name}: TBank OFX without an ACCTID")
        return ids
    if bank == "santander":
        return (santander.iban(path),)
    return (None,)


def _normalize_id(value: str) -> str:
    return value.replace(" ", "").casefold()


def _entry_matches(
    entry: AccountEntry, bank: str, kind: AccountKind, identity: str | None, filename: str
) -> bool:
    if entry.bank != bank or entry.kind != kind:
        return False
    candidate_id = entry.acct_id or entry.iban
    if identity is not None and candidate_id is not None:
        return _normalize_id(identity) == _normalize_id(candidate_id)
    if entry.file is not None:
        return fnmatch.fnmatchcase(filename.casefold(), entry.file.casefold())
    return False


def _id_description(identity: str | None) -> str:
    return f"in-file id {identity}" if identity is not None else "no in-file id"


def _hint(bank: str, kind: AccountKind, identity: str | None, stem: str) -> str:
    parts = [f'bank = "{bank}"']
    if bank == "tbank" and identity is not None:
        parts.append(f'acct_id = "{identity}"')
    elif bank == "santander" and identity is not None:
        parts.append(f'iban = "{identity}"')
    else:
        parts.append(f'file = "{stem}*"')
    if kind != "current":
        parts.append(f'kind = "{kind}"')
    return ", ".join(parts)


def _resolve(
    path: Path, bank: str, kind: AccountKind, identity: str | None, accounts: list[AccountEntry]
) -> DiscoveredFile:
    matches = [
        entry for entry in accounts if _entry_matches(entry, bank, kind, identity, path.name)
    ]
    prefix = f"{path.name}: format {bank}/{kind}, {_id_description(identity)}"
    if len(matches) > 1:
        names = ", ".join(entry.moneywiz for entry in matches)
        raise DiscoveryError(f"{prefix}; matches several [[accounts]] entries: {names}")
    if not matches:
        hint = _hint(bank, kind, identity, path.stem)
        raise DiscoveryError(f"{prefix}; no [[accounts]] entry matches; add one with {hint}")
    entry = matches[0]
    candidate_id = entry.acct_id or entry.iban
    if identity is not None and candidate_id is not None:
        evidence = f"in-file id {identity}"
    else:
        evidence = f"file name matches {entry.file!r}"
    return DiscoveredFile(
        path=path,
        bank=bank,
        kind=kind,
        identity=identity,
        account=entry.moneywiz,
        evidence=evidence,
    )


def discover(folder: Path, config: Config) -> Discovery:
    """Sniff and resolve every statement file in `folder`.

    Resolution failures are collected and raised together as one DiscoveryError, one file
    per line. A StatementFormatError while reading a file's identities propagates at once.
    """
    files: list[DiscoveredFile] = []
    skipped: list[PassedFile] = []
    unrecognized: list[PassedFile] = []
    failures: list[str] = []
    for path in sorted(folder.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        if path.suffix.casefold() not in STATEMENT_SUFFIXES:
            continue
        result = sniff(path)
        if isinstance(result, Passed):
            target = skipped if result.recognized else unrecognized
            target.append(PassedFile(path=path, reason=result.reason))
            continue
        bank, kind = result
        try:
            identities = file_identities(path, bank)
        except DiscoveryError as exc:
            failures.append(str(exc))
            continue
        for identity in identities:
            try:
                files.append(_resolve(path, bank, kind, identity, config.accounts))
            except DiscoveryError as exc:
                failures.append(str(exc))
    if failures:
        raise DiscoveryError("\n".join(failures))
    return Discovery(files=tuple(files), skipped=tuple(skipped), unrecognized=tuple(unrecognized))
