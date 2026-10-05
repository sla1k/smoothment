import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from smoothment import config as config_module
from smoothment.config import Config, load_config
from smoothment.export import COLUMNS
from smoothment.statement.model import ParsedStatement
from smoothment.statement.parsers import PARSERS, wise
from tests.moneywiz_fixture import FxAccount, FxCategory, FxPayee, FxTransaction, build_db

FIXTURES = Path(__file__).parent / "fixtures"

MakeDb = Callable[[list[FxAccount], list[FxCategory], list[FxPayee], list[FxTransaction]], Path]

STATEMENT_CONFIG = """\
[[accounts]]
bank = "revolut"
moneywiz = "Shared"
file = "revolut_shared*"

[[accounts]]
bank = "revolut"
moneywiz = "Revolut"
file = "revolut_eur*"

[[accounts]]
bank = "revolut"
kind = "savings"
moneywiz = "Safety"
file = "revolut_saves*"

[[accounts]]
bank = "wise"
moneywiz = "Wise"
file = "wise*"

[[accounts]]
bank = "tbank"
moneywiz = "Black"
acct_id = "40817810000000000001"

[[accounts]]
bank = "tbank"
moneywiz = "Platinum"
acct_id = "0500000001"

[[accounts]]
bank = "bbva"
moneywiz = "BBVA"
file = "bbva*"

[[accounts]]
bank = "santander"
moneywiz = "Santander"
iban = "ES00 0000 0000 0000 0000 0000"

[pockets.accounts.Shared]
Travel = "Travel"

[pockets.accounts.Revolut]
"Flexible Cash Funds" = "Safety"

[banks.revolut]
payee = "Revolut"
[banks.wise]
payee = "Wise"
[banks.tbank]
payee = "TBank"
"""


ROUNDUPS_HEADER = (
    "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance"
)
ROUNDUPS_CSV = "\n".join(
    [
        ROUNDUPS_HEADER,
        "Card Payment,Current,2026-08-01 09:00:00,2026-08-01 09:00:00,Coffee Corner,"
        "-3.50,0.00,EUR,COMPLETED,96.50",
        "Transfer,Current,2026-08-01 10:00:00,2026-08-01 10:00:00,To EUR Travel,"
        "-0.10,0.00,EUR,COMPLETED,96.40",
        "Transfer,Deposit,2026-08-01 10:00:00,2026-08-01 10:00:00,To EUR Travel,"
        "0.10,0.00,EUR,COMPLETED,0.10",
        "Transfer,Current,2026-08-02 10:00:00,2026-08-02 10:00:00,To EUR Travel,"
        "-0.20,0.00,EUR,COMPLETED,96.20",
        "Transfer,Deposit,2026-08-02 10:00:00,2026-08-02 10:00:00,To EUR Travel,"
        "0.20,0.00,EUR,COMPLETED,0.30",
        "Transfer,Current,2026-08-03 10:00:00,2026-08-03 10:00:00,To EUR Travel,"
        "-0.30,0.00,EUR,COMPLETED,95.90",
        "Transfer,Deposit,2026-08-03 10:00:00,2026-08-03 10:00:00,To EUR Travel,"
        "0.30,0.00,EUR,COMPLETED,0.60",
    ]
)

ROUNDUPS_CONFIG = """\
[[accounts]]
bank = "revolut"
moneywiz = "Shared"
file = "revolut_shared*"

[pockets.accounts.Shared]
Travel = "Travel"
"""


@pytest.fixture(autouse=True)
def no_real_moneywiz_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the default MoneyWiz store at a file that does not exist."""
    missing = tmp_path / "no-moneywiz" / "MoneyWiz_iCloud.sqlite"
    monkeypatch.setattr(config_module, "DEFAULT_DB_PATH", missing)


@pytest.fixture
def roundups_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "2026_08"
    folder.mkdir()
    (folder / "revolut_shared.csv").write_text(ROUNDUPS_CSV)
    return folder


@pytest.fixture
def moneywiz_db(tmp_path: Path) -> MakeDb:
    def make(
        accounts: list[FxAccount],
        categories: list[FxCategory],
        payees: list[FxPayee],
        transactions: list[FxTransaction],
    ) -> Path:
        path = tmp_path / "MoneyWiz_iCloud.sqlite"
        build_db(path, accounts, categories, payees, transactions)
        return path

    return make


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[[str], Config]:
    def make(accounts_toml: str) -> Config:
        path = tmp_path / "smoothment.toml"
        path.write_text('[owner]\nnames = ["Sample Owner"]\n' + accounts_toml)
        return load_config(path)

    return make


@pytest.fixture
def statement_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "2026_09"
    folder.mkdir()
    shutil.copy(FIXTURES / "revolut_pockets.csv", folder / "revolut_shared.csv")
    shutil.copy(FIXTURES / "revolut_transfers.csv", folder / "revolut_eur.csv")
    shutil.copy(FIXTURES / "revolut_savings.csv", folder / "revolut_saves.csv")
    shutil.copy(FIXTURES / "revolut_pocket_export.csv", folder / "revolut_travel.csv")
    shutil.copy(FIXTURES / "wise.csv", folder / "wise.csv")
    shutil.copy(FIXTURES / "tbank_two_accounts.ofx", folder / "tbank_two_accounts.ofx")
    shutil.copy(FIXTURES / "bbva_en.xlsx", folder / "bbva.xlsx")
    shutil.copy(FIXTURES / "santander.xlsx", folder / "santander.xlsx")
    (folder / "moneywiz_import.csv").write_text(",".join(COLUMNS) + "\n")
    (folder / "notes.pdf").write_bytes(b"%PDF-1.4\n")
    (folder / "random.csv").write_text("a,b,c\n")
    (folder / ".DS_Store").write_bytes(b"\x00\x00\x00\x00")
    return folder


def inflate_wise_input_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the Wise parser claim one more input row than it accounts for."""

    def parse(path: Path, account: str, identity: str | None) -> ParsedStatement:
        statement = wise.parse_current(path, account, identity)
        return replace(statement, input_rows=statement.input_rows + 1)

    monkeypatch.setitem(PARSERS, ("wise", "current"), parse)
