from decimal import Decimal
from pathlib import Path

import pytest

from smoothment import config as config_module
from smoothment.config import DEFAULT_DB_PATH, Config, ConfigError, MoneyWizSettings, load_config

MINIMAL = """
[owner]
names = ["Sample Owner"]

[[accounts]]
bank = "tbank"
acct_id = "40817810000000000001"
moneywiz = "Black"
"""


def test_minimal_config_uses_default_db_path(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL)
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.moneywiz.db == config_module.DEFAULT_DB_PATH
    assert cfg.owner.names == ["Sample Owner"]
    assert cfg.accounts[0].moneywiz == "Black"
    assert cfg.accounts[0].acct_id == "40817810000000000001"
    assert cfg.moneywiz.single_leg_creates_reciprocal is None


def test_tests_never_default_to_the_real_store(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL)
    cfg = load_config(tmp_path / "smoothment.toml")
    bare = Config.model_validate({"owner": {"names": ["Sample Owner"]}, "path": tmp_path})
    for db in (cfg.moneywiz.db, MoneyWizSettings().db, bare.moneywiz.db):
        assert db != DEFAULT_DB_PATH
        assert db.is_relative_to(tmp_path)
        assert not db.exists()


def test_tilde_in_db_path_is_expanded(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL + '\n[moneywiz]\ndb = "~/x/y.sqlite"\n')
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.moneywiz.db == Path("~/x/y.sqlite").expanduser()
    assert "~" not in str(cfg.moneywiz.db)


def test_probe_overlay_wins(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL)
    (tmp_path / "smoothment.probe.toml").write_text(
        "[moneywiz]\nsingle_leg_creates_reciprocal = true\nmemo_lands_in_notes = false\n"
    )
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.moneywiz.single_leg_creates_reciprocal is True
    assert cfg.moneywiz.memo_lands_in_notes is False
    assert cfg.moneywiz.two_legs_link_once is None


def test_flat_entry_with_iban_only_loads(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        '[owner]\nnames=["A"]\n[[accounts]]\nbank="santander"\niban="ES0201820200"'
        '\nmoneywiz="Santander"\n'
    )
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.accounts[0].iban == "ES0201820200"
    assert cfg.accounts[0].acct_id is None
    assert cfg.accounts[0].file is None


def test_kind_defaults_to_current(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL)
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.accounts[0].kind == "current"


def test_kind_can_be_set_to_savings_or_pocket(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        '[owner]\nnames=["A"]\n[[accounts]]\nbank="revolut"\nkind="savings"\nfile="sav*"'
        '\nmoneywiz="Safety"\n'
    )
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.accounts[0].kind == "savings"


def test_account_without_identity_evidence_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        '[owner]\nnames=["A"]\n[[accounts]]\nbank="tbank"\nmoneywiz="Black"\n'
    )
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "smoothment.toml")
    assert "accounts" in str(exc.value)
    assert "acct_id" in str(exc.value)


def test_invalid_kind_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        '[owner]\nnames=["A"]\n[[accounts]]\nbank="tbank"\nkind="weird"\nacct_id="123"'
        '\nmoneywiz="Black"\n'
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path / "smoothment.toml")


def test_old_nested_match_shape_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        '[owner]\nnames=["A"]\n[[accounts]]\nbank="tbank"\nmatch={acct_id="123"}'
        '\nmoneywiz="Black"\n'
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path / "smoothment.toml")


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "nope.toml")
    assert "nope.toml" in str(exc.value)


def test_invalid_toml_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text("[owner\nnames = 1")
    with pytest.raises(ConfigError):
        load_config(tmp_path / "smoothment.toml")


def test_unknown_bank_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        '[owner]\nnames=["A"]\n[[accounts]]\nbank="revolute"\nfile="rev*"\nmoneywiz="Main"\n'
    )
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "smoothment.toml")
    assert "accounts.0.bank" in str(exc.value)


def test_pockets_banks_cash_transfers_default_when_absent(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL)
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.pockets.roundup_max == Decimal("1.00")
    assert cfg.pockets.accounts == {}
    assert cfg.banks == {}
    assert cfg.categories == {}
    assert cfg.cash is None
    assert cfg.transfers.window_days == 3
    assert cfg.transfers.tolerance == Decimal("0.02")


def test_full_example_of_new_tables_loads(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        MINIMAL
        + SHARED_ACCOUNT
        + """
[pockets]
roundup_max = "2.50"

[pockets.accounts.Shared]
Travel = "Travel"

[banks.tbank]
payee = "TBank"

[cash]
account = "Cash"

[transfers]
window_days = 5
tolerance = "0.05"
"""
    )
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.pockets.roundup_max == Decimal("2.50")
    assert cfg.pockets.accounts == {"Shared": {"Travel": "Travel"}}
    assert cfg.banks["tbank"].payee == "TBank"
    assert cfg.cash is not None
    assert cfg.cash.account == "Cash"
    assert cfg.transfers.window_days == 5
    assert cfg.transfers.tolerance == Decimal("0.05")


def test_banks_keyed_by_unsupported_bank_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL + '\n[banks.revolute]\npayee = "Revolut"\n')
    with pytest.raises(ConfigError):
        load_config(tmp_path / "smoothment.toml")


def test_negative_roundup_max_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL + '\n[pockets]\nroundup_max = "-1.00"\n')
    with pytest.raises(ConfigError):
        load_config(tmp_path / "smoothment.toml")


def test_negative_transfer_tolerance_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL + '\n[transfers]\ntolerance = "-0.01"\n')
    with pytest.raises(ConfigError):
        load_config(tmp_path / "smoothment.toml")


def test_negative_window_days_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL + "\n[transfers]\nwindow_days = -1\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path / "smoothment.toml")


def test_short_phone_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        '[owner]\nnames=["A"]\nphones = ["12345"]\n'
        '[[accounts]]\nbank="tbank"\nacct_id="40817810000000000001"\nmoneywiz="Black"\n'
    )
    with pytest.raises(ConfigError):
        load_config(tmp_path / "smoothment.toml")


def test_owner_phones_are_normalized_to_digits_only(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        '[owner]\nnames=["A"]\nphones = ["+00 700 000 0000"]\n'
        '[[accounts]]\nbank="tbank"\nacct_id="40817810000000000001"\nmoneywiz="Black"\n'
    )
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.owner.phones == ["007000000000"]


SHARED_ACCOUNT = '\n[[accounts]]\nbank = "revolut"\nfile = "revolut_shared*"\nmoneywiz = "Shared"\n'


def test_pockets_accounts_round_trip(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        MINIMAL + SHARED_ACCOUNT + '\n[pockets.accounts.Shared]\nTravel = "Travel"\n'
    )
    cfg = load_config(tmp_path / "smoothment.toml")
    assert cfg.pockets.accounts == {"Shared": {"Travel": "Travel"}}


def test_pockets_keyed_by_an_unknown_account_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        MINIMAL + SHARED_ACCOUNT + '\n[pockets.accounts.Shraed]\nTravel = "Travel"\n'
    )
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "smoothment.toml")
    assert "pockets.accounts.Shraed" in str(exc.value)
    assert "not the moneywiz name of a configured account" in str(exc.value)


def test_pocket_mapped_to_its_own_account_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(
        MINIMAL + SHARED_ACCOUNT + '\n[pockets.accounts.Shared]\nTravel = "Shared"\n'
    )
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "smoothment.toml")
    assert "pockets.accounts.Shared.Travel" in str(exc.value)
    assert "maps to its own account" in str(exc.value)


def test_leftover_categories_table_is_accepted_and_ignored(tmp_path: Path) -> None:
    (tmp_path / "smoothment.toml").write_text(MINIMAL + '\n[categories]\nfee = "Bank > Fee"\n')

    cfg = load_config(tmp_path / "smoothment.toml")

    assert cfg.categories == {"fee": "Bank > Fee"}
