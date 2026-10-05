import os
from pathlib import Path

import pytest

from smoothment.config import load_config
from smoothment.convert import run_convert
from smoothment.statement.discover import DiscoveryError
from smoothment.statement.model import StatementFormatError

REPLAY = os.environ.get("SMOOTHMENT_REPLAY")
SKIP = {
    name.strip() for name in os.environ.get("SMOOTHMENT_REPLAY_SKIP", "").split(",") if name.strip()
}

pytestmark = pytest.mark.skipif(not REPLAY, reason="set SMOOTHMENT_REPLAY=<finance folder>")


def test_replay_every_dated_folder() -> None:
    root = Path(REPLAY or "").expanduser()
    config = load_config(root / "smoothment.toml")
    folders = sorted(p for p in root.iterdir() if p.is_dir() and p.name[:4].isdigit())
    assert folders, f"no dated folders under {root}"
    notes: list[str] = []
    failures: list[str] = []
    for folder in folders:
        try:
            result = run_convert(folder, config, dry_run=True)
        except (DiscoveryError, StatementFormatError) as exc:
            if folder.name in SKIP:
                notes.append(
                    f"{folder.name}: skipped by SMOOTHMENT_REPLAY_SKIP ({type(exc).__name__})"
                )
            else:
                failures.append(f"{folder.name}: {type(exc).__name__}: {exc}")
            continue
        for file in result.unbalanced:
            accounting = file.accounting
            failures.append(
                f"{folder.name}/{file.statement.file.name}: row accounting "
                f"{accounting.source_rows} input rows, {accounting.accounted} accounted"
            )
        for file in result.files:
            for mismatch in file.mismatches:
                failures.append(
                    f"{folder.name}/{mismatch.file.name}: balance mismatch in chain "
                    f"{mismatch.chain} at row {mismatch.row.line}"
                )
        mismatches = sum(len(file.mismatches) for file in result.files)
        notes.append(
            f"{folder.name}: {len(result.files)} statements, {len(result.export_rows)} rows, "
            f"{mismatches} balance mismatches, {len(result.discovery.unrecognized)} unrecognized, "
            f"{len(result.transfers)} transfers, {len(result.lumps)} lumps, "
            f"{len(result.unmatched)} unmatched"
        )
    print("\n" + "\n".join(notes))
    assert not failures, "\n".join(failures)
