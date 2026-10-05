from pathlib import Path

import pytest

from smoothment.config import MoneyWizSettings
from smoothment.moneywiz.locate import MoneyWizRunningError, is_moneywiz_running, open_snapshot
from smoothment.moneywiz.reader import MoneyWizStoreError
from tests.conftest import MakeDb
from tests.moneywiz_fixture import FxAccount


def test_is_running_detects_process_name() -> None:
    assert is_moneywiz_running(lambda: ["Finder", "MoneyWiz"]) is True
    assert is_moneywiz_running(lambda: ["Finder"]) is False


def test_open_snapshot_refuses_when_running(
    moneywiz_db: MakeDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = moneywiz_db([FxAccount(1, "Revolut")], [], [], [])
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", lambda: ["MoneyWiz"])
    with pytest.raises(MoneyWizRunningError):
        open_snapshot(MoneyWizSettings(db=path))
    snap = open_snapshot(MoneyWizSettings(db=path), allow_running=True)
    assert snap.account("Revolut") is not None


def test_open_snapshot_missing_file_mentions_full_disk_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    with pytest.raises(MoneyWizStoreError) as exc:
        open_snapshot(MoneyWizSettings(db=tmp_path / "nope" / "MoneyWiz_iCloud.sqlite"))
    assert "Full Disk Access" in str(exc.value)


def test_open_snapshot_protected_container_mentions_full_disk_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)

    def _raise_permission_error(_path: Path) -> list[str]:
        raise PermissionError("denied")

    monkeypatch.setattr("smoothment.moneywiz.locate.os.listdir", _raise_permission_error)
    with pytest.raises(MoneyWizStoreError) as exc:
        open_snapshot(MoneyWizSettings(db=tmp_path / "MoneyWiz_iCloud.sqlite"))
    assert "container is protected" in str(exc.value)


def test_open_snapshot_readable_folder_without_file_says_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("smoothment.moneywiz.locate._pgrep_names", list)
    with pytest.raises(MoneyWizStoreError) as exc:
        open_snapshot(MoneyWizSettings(db=tmp_path / "MoneyWiz_iCloud.sqlite"))
    assert "file is missing" in str(exc.value)
