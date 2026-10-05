import os
import subprocess
from collections.abc import Callable

from smoothment.config import MoneyWizSettings
from smoothment.moneywiz.model import MoneyWizSnapshot
from smoothment.moneywiz.reader import MoneyWizStoreError, read_snapshot

PROCESS_NAME = "MoneyWiz"


class MoneyWizRunningError(Exception):
    """MoneyWiz is open; close it before reading the store."""


def _pgrep_names() -> list[str]:
    result = subprocess.run(
        ["pgrep", "-x", "-l", PROCESS_NAME], capture_output=True, text=True, check=False
    )
    return [line.split(maxsplit=1)[1] for line in result.stdout.splitlines() if " " in line]


def is_moneywiz_running(pgrep: Callable[[], list[str]] = _pgrep_names) -> bool:
    return PROCESS_NAME in pgrep()


def open_snapshot(settings: MoneyWizSettings, *, allow_running: bool = False) -> MoneyWizSnapshot:
    if not allow_running and is_moneywiz_running(_pgrep_names):
        raise MoneyWizRunningError(
            "MoneyWiz is running. Close it, or pass --allow-running for a read-only look."
        )
    db = settings.db
    if not db.is_file():
        try:
            os.listdir(db.parent)
        except PermissionError:
            hint = " (the container is protected: grant Full Disk Access to the terminal app)"
        except FileNotFoundError:
            hint = (
                " (the folder does not exist; if it is the MoneyWiz container,"
                " grant Full Disk Access to the terminal app)"
            )
        else:
            hint = " (the folder exists but the file is missing)"
        raise MoneyWizStoreError(f"MoneyWiz store not found: {db}{hint}")
    return read_snapshot(db)
