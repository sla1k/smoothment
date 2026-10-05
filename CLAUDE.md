# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smoothment converts the bank statements downloaded every month (Revolut, Wise, TBank, BBVA,
Santander, Sovcombank; CSV, OFX, XLSX, XLS) into one MoneyWiz import CSV. It detects transfers
between the owner's accounts, folds round-ups, savings interest and fees into lumps, and reports
what it could not work out. `verify` compares the same folder with a read-only copy of the
MoneyWiz store after the import and lists what is missing, wrong or extra. The project sits at
the repository root (Python 3.14, uv, `src/` layout). `README.md` has setup and the monthly routine;
`docs/reference.md` has the options, reports, rules, config and exit codes;
`docs/supported-banks.md` lists the banks and their quirks. User docs are short reference, not
implementation notes.

## Commands

Run from the repository root:

```bash
uv run ruff format src tests && uv run pytest -q     # the gate
uv run smoothment convert <folder> [--dry-run]       # writes <folder>/moneywiz_import.csv
uv run smoothment verify <folder>
```

`uv run pytest` also runs ruff and ty gates. `tests/test_replay.py` needs real statements and is
skipped unless `SMOOTHMENT_REPLAY` is set; do not set it.

## Architecture

Pipeline in `src/smoothment`: discover files, parse, classify, lump, link, export.

- `statement/`: `discover.py` matches each file to an `[[accounts]]` entry; `parsers/` has one
  parser per bank format; `balance.py` checks running balances; `sheets.py` reads XLS/XLSX.
- `classify/`: tags each row with a kind (`purchase`, `own_transfer`, `fee`, ...); `owner.py` is
  the gate that decides a row is a transfer between the owner's own accounts.
- `lumps.py`: folds round-ups, savings interest and fees into one row per statement.
- `link.py`: pairs transfer legs across statements (window and tolerance from config).
- `export.py`: builds the CSV rows, memo tags (`smt:`) and writes the file.
- `convert.py`: orchestrates the pipeline and builds `ConvertResult`.
- `reconcile.py`: matches statement rows, transfers and lumps to MoneyWiz transactions (by tag,
  then by account, amount and date); also reads lump cut-offs.
- `verify.py`: runs `convert`, reconciles against the store, and works out balance differences.
- `moneywiz/`: read-only reader of the MoneyWiz SQLite store (`locate.py` refuses to read while
  MoneyWiz runs).
- `probe/`: one-time experiment on MoneyWiz import behaviour; already run, left as it is.
- `report.py`: Rich output for `convert` and `verify`. `cli.py`: Typer commands.

The design is in `docs/design.md`.

## Standing rules

- The tool never writes to the MoneyWiz store; it reads a copy.
- Tests use synthetic data only and never read real statements or the real store.
- Money is `Decimal`.
- Pipeline records are frozen slotted dataclasses; config is pydantic with strict models.
- No comments that restate the code.
