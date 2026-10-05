# Smoothment

Turns a month of downloaded bank statements into one CSV for MoneyWiz, then checks that MoneyWiz
holds what the banks say.

- `smoothment convert <folder>` reads every statement in the folder, pairs transfers between your
  own accounts across banks, maps Revolut pockets to their own accounts, folds round-ups, savings
  interest and fees into one row per statement, checks running balances, and writes
  `moneywiz_import.csv`.
- `smoothment verify <folder>` runs after the import and lists what MoneyWiz is missing, has wrong
  or has extra, and whether each balance agrees with the bank.

It only ever reads MoneyWiz's database, from a temporary copy. It is a personal tool, built around
one set of banks and accounts.

Supported banks: six so far, see [which ones and their quirks](docs/supported-banks.md).

## Setup

You need macOS with MoneyWiz, Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/sla1k/smoothment.git
cd smoothment
uv sync
```

Give your terminal app Full Disk Access (MoneyWiz keeps its database in a protected container).
The default database path is that of the Setapp edition of MoneyWiz; set `[moneywiz] db` for
another.

Keep one folder per month next to a `smoothment.toml`:

```
Finance/
├── smoothment.toml
├── 2026_08/
└── 2026_09/
```

The config holds your name as it appears on statements, and one entry per account you download
statements for (`--config <path>` points elsewhere).

```toml
[owner]
names = ["Your Name"]

[[accounts]]
bank = "revolut"
moneywiz = "Shared"        # the account name in MoneyWiz
file = "revolut_shared*"   # file name glob

[[accounts]]
bank = "tbank"
moneywiz = "Black"
acct_id = "40817810000000000001"   # read from inside the file
```

Pockets, cash, bank payees and transfer limits are optional; see the
[config file reference](docs/reference.md#config-file).

## Every month

1. Download each account's statement into a new month folder, for example `Finance/2026_09/`.
2. Back up MoneyWiz (Settings > Database & Export). An import cannot be undone.
3. Quit MoneyWiz, then preview: `uv run smoothment convert <folder> --dry-run`.
4. Run it for real: `uv run smoothment convert <folder>`.
5. Drag `moneywiz_import.csv` onto MoneyWiz and import it (see below).
6. Quit MoneyWiz and run `uv run smoothment verify <folder>`. Fix what it lists and run it again
   until it says `Nothing to fix`.

### Importing into MoneyWiz

- Choose **Advanced import**, not Quick import, which makes a new payee for every unknown string.
- Pick the `yyyy-MM-dd` date format if asked.
- Link every account to an existing one; `convert` has already checked they all exist.
- Link unknown payees to yours, and pick a category per payee. The CSV has no categories on
  purpose; MoneyWiz remembers both choices for next time.
- Skip the duplicates MoneyWiz offers when the file overlaps earlier imports.

Each row's Memo carries an `smt:` tag (shown once you enable Memo in Settings > Transaction
layout). Leave it alone: `verify` relies on it.

## Docs

- [Supported banks](docs/supported-banks.md): formats, matching and per-bank details.
- [Reference](docs/reference.md): options, reports, rules, config file, exit codes.
- [Design](docs/design.md) and [MoneyWiz database notes](docs/moneywiz-schema.md).

## Development

```bash
uv run ruff format src tests && uv run pytest   # pytest also runs ruff and ty
```

Tests use synthetic data only. To also replay `convert --dry-run` over your real monthly folders
(`SMOOTHMENT_REPLAY_SKIP` tolerates format errors in the folders it lists):

```bash
SMOOTHMENT_REPLAY=~/Finance SMOOTHMENT_REPLAY_SKIP=2025_12 \
    uv run pytest tests/test_replay.py -s
```

## License

MIT, see [LICENSE](LICENSE).
