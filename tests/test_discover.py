from collections.abc import Callable
from pathlib import Path

import pytest

from smoothment.config import Config
from smoothment.statement.discover import (
    DiscoveryError,
    Passed,
    discover,
    file_identities,
    sniff,
)
from smoothment.statement.model import StatementFormatError
from smoothment.statement.parsers import PARSERS
from tests.conftest import FIXTURES, STATEMENT_CONFIG


def test_sniff_recognizes_each_fixture() -> None:
    assert sniff(FIXTURES / "revolut_pockets.csv") == ("revolut", "current")
    assert sniff(FIXTURES / "revolut_savings.csv") == ("revolut", "savings")
    assert sniff(FIXTURES / "wise.csv") == ("wise", "current")
    assert sniff(FIXTURES / "tbank_two_accounts.ofx") == ("tbank", "current")
    assert sniff(FIXTURES / "bbva_en.xlsx") == ("bbva", "current")
    assert sniff(FIXTURES / "santander.xlsx") == ("santander", "current")


def test_sniff_pocket_export_is_passed_recognized() -> None:
    result = sniff(FIXTURES / "revolut_pocket_export.csv")
    assert isinstance(result, Passed)
    assert result.recognized is True


def test_sniff_own_output_is_passed_recognized(tmp_path: Path) -> None:
    from smoothment.export import COLUMNS

    path = tmp_path / "moneywiz_import.csv"
    path.write_text(",".join(COLUMNS) + "\n")

    result = sniff(path)
    assert isinstance(result, Passed)
    assert result.recognized is True


def test_sniff_random_csv_is_unrecognized(tmp_path: Path) -> None:
    path = tmp_path / "random.csv"
    path.write_text("a,b,c\n")

    result = sniff(path)
    assert isinstance(result, Passed)
    assert result.recognized is False


def test_sniff_non_tbank_ofx_is_unrecognized(tmp_path: Path) -> None:
    path = tmp_path / "converted_transactions.ofx"
    path.write_text("<OFX><BANKID>OTHERBANK</BANKID></OFX>")

    result = sniff(path)
    assert isinstance(result, Passed)
    assert result.recognized is False


def test_sniff_non_zip_xlsx_is_unrecognized(tmp_path: Path) -> None:
    path = tmp_path / "bad.xlsx"
    path.write_bytes(b"not a zip file")

    result = sniff(path)
    assert isinstance(result, Passed)
    assert result.recognized is False


def test_sniff_non_biff_xls_is_unrecognized(tmp_path: Path) -> None:
    path = tmp_path / "bad.xls"
    path.write_bytes(b"just text, not xls")

    result = sniff(path)
    assert isinstance(result, Passed)
    assert result.recognized is False


def test_sniff_renamed_wise_file_still_sniffs_as_wise(tmp_path: Path) -> None:
    path = tmp_path / "revolut_eur.csv"
    path.write_bytes((FIXTURES / "wise.csv").read_bytes())

    assert sniff(path) == ("wise", "current")


def test_file_identities_tbank_returns_both_accounts() -> None:
    identities = file_identities(FIXTURES / "tbank_two_accounts.ofx", "tbank")
    assert identities == ("40817810000000000001", "0500000001")


def test_file_identities_santander_returns_iban() -> None:
    identities = file_identities(FIXTURES / "santander.xlsx", "santander")
    assert identities == ("ES0000000000000000000000",)


def test_file_identities_wise_returns_none() -> None:
    identities = file_identities(FIXTURES / "wise.csv", "wise")
    assert identities == (None,)


def test_file_identities_tbank_without_acctid_raises(tmp_path: Path) -> None:
    path = tmp_path / "no_acctid.ofx"
    path.write_text("<OFX><BANKID>T-BANK</BANKID></OFX>")

    with pytest.raises(DiscoveryError, match="ACCTID"):
        file_identities(path, "tbank")


def test_parsers_keys_match_the_seven_pairs() -> None:
    assert set(PARSERS) == {
        ("revolut", "current"),
        ("revolut", "savings"),
        ("wise", "current"),
        ("tbank", "current"),
        ("bbva", "current"),
        ("santander", "current"),
        ("sovcombank", "current"),
    }


def test_discover_resolves_all_files(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    config = make_config(STATEMENT_CONFIG)

    result = discover(statement_folder, config)

    assert [f.path.name for f in result.files] == [
        "bbva.xlsx",
        "revolut_eur.csv",
        "revolut_saves.csv",
        "revolut_shared.csv",
        "santander.xlsx",
        "tbank_two_accounts.ofx",
        "tbank_two_accounts.ofx",
        "wise.csv",
    ]
    by_name = {f.path.name: f for f in result.files if f.path.name != "tbank_two_accounts.ofx"}
    assert by_name["bbva.xlsx"].account == "BBVA"
    assert by_name["revolut_saves.csv"].account == "Safety"
    assert by_name["revolut_saves.csv"].kind == "savings"
    assert by_name["revolut_shared.csv"].account == "Shared"
    assert by_name["revolut_eur.csv"].account == "Revolut"
    assert by_name["santander.xlsx"].account == "Santander"
    assert by_name["santander.xlsx"].identity == "ES0000000000000000000000"
    assert by_name["santander.xlsx"].evidence.startswith("in-file id")
    assert by_name["wise.csv"].account == "Wise"

    tbank_files = [f for f in result.files if f.path.name == "tbank_two_accounts.ofx"]
    assert [f.account for f in tbank_files] == ["Black", "Platinum"]

    assert [f.path.name for f in result.skipped] == ["moneywiz_import.csv", "revolut_travel.csv"]
    assert [f.path.name for f in result.unrecognized] == ["random.csv"]


def test_discover_two_matching_entries_raises(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    extra = STATEMENT_CONFIG + '\n[[accounts]]\nbank = "wise"\nmoneywiz = "Wise USD"\nfile = "w*"\n'
    config = make_config(extra)

    with pytest.raises(DiscoveryError, match=r"wise\.csv.*several.*Wise, Wise USD"):
        discover(statement_folder, config)


def test_discover_no_matching_entry_raises(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    without_wise = STATEMENT_CONFIG.replace(
        '[[accounts]]\nbank = "wise"\nmoneywiz = "Wise"\nfile = "wise*"\n\n', ""
    )
    assert without_wise != STATEMENT_CONFIG
    config = make_config(without_wise)

    with pytest.raises(DiscoveryError, match=r'wise\.csv: format wise/current.*bank = "wise"'):
        discover(statement_folder, config)


def test_discover_id_match_overrides_wildcard_glob(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    with_wildcard = STATEMENT_CONFIG.replace(
        'moneywiz = "Black"\nacct_id = "40817810000000000001"',
        'moneywiz = "Black"\nacct_id = "40817810000000000001"\nfile = "*"',
    )
    assert with_wildcard != STATEMENT_CONFIG
    config = make_config(with_wildcard)

    result = discover(statement_folder, config)

    tbank_files = [f for f in result.files if f.bank == "tbank"]
    assert {f.account for f in tbank_files} == {"Black", "Platinum"}


REVOLUT_EXTRA_COLUMN = (
    "Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance,"
    "Extra\n"
    "Card Payment,Current,2026-08-01 10:00:00,2026-08-01 12:00:00,Coffee,-3.50,0.00,EUR,"
    "COMPLETED,96.50,x\n"
)


def test_sniff_revolut_current_by_header_prefix(tmp_path: Path) -> None:
    path = tmp_path / "revolut_shared.csv"
    path.write_text(REVOLUT_EXTRA_COLUMN)

    assert sniff(path) == ("revolut", "current")


def test_discover_reports_every_resolution_failure_at_once(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    without = STATEMENT_CONFIG.replace(
        '[[accounts]]\nbank = "wise"\nmoneywiz = "Wise"\nfile = "wise*"\n\n', ""
    ).replace('[[accounts]]\nbank = "bbva"\nmoneywiz = "BBVA"\nfile = "bbva*"\n\n', "")
    assert without.count("[[accounts]]") == STATEMENT_CONFIG.count("[[accounts]]") - 2
    config = make_config(without)

    with pytest.raises(DiscoveryError) as exc:
        discover(statement_folder, config)

    lines = str(exc.value).splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("bbva.xlsx: ")
    assert lines[1].startswith("wise.csv: ")


TBANK_BLOCK_WITHOUT_ACCTID = """<?xml version="1.0" encoding="UTF-8"?>
<OFX>
  <BANKMSGSRSV1>
    <STMTTRNRS>
      <STMTRS>
        <CURDEF>RUB</CURDEF>
        <BANKACCTFROM>
          <BANKID>T-BANK</BANKID>
          <ACCTID>40817810000000000001</ACCTID>
        </BANKACCTFROM>
      </STMTRS>
    </STMTTRNRS>
    <STMTTRNRS>
      <STMTRS>
        <CURDEF>RUB</CURDEF>
        <BANKACCTFROM>
          <BANKID>T-BANK</BANKID>
        </BANKACCTFROM>
      </STMTRS>
    </STMTTRNRS>
  </BANKMSGSRSV1>
</OFX>
"""


def test_discover_propagates_tbank_block_without_acctid(
    statement_folder: Path, make_config: Callable[[str], Config]
) -> None:
    (statement_folder / "tbank_broken.ofx").write_text(TBANK_BLOCK_WITHOUT_ACCTID)
    config = make_config(STATEMENT_CONFIG)

    with pytest.raises(StatementFormatError) as exc:
        discover(statement_folder, config)

    assert exc.value.column == "ACCTID"
    assert exc.value.file.name == "tbank_broken.ofx"
