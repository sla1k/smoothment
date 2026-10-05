# Design

## Goal

Statements converted by rules that are never checked against the target app drift: transfers lose
their pair, pocket round-ups become expenses, balances go off, and every fix is made blind.
Smoothment closes the loop. It reads MoneyWiz before the export (to skip what is already there and
to check account names) and after the import (`verify`, to report exactly what to fix).

## Decisions

| # | Decision |
|---|---|
| D1 | Target app: MoneyWiz, through its CSV import. The pipeline is generic; MoneyWiz is the export profile. |
| D2 | Statements are downloaded by hand. No bank APIs or MoneyWiz Online Banking: the sync feed creates parallel accounts, cannot see Revolut pockets, and forks payee names. |
| D3 | One parser per bank, in code, not a declarative mapping. A bank's statement formats (Revolut `current`, `savings`) are account kinds, not separate banks. |
| D4 | One TOML config next to the monthly statement folders: owner, accounts, pockets, rules. |
| D5 | The MoneyWiz database is read live, from a copy, while MoneyWiz is closed. Never written. |
| D6 | Pocket round-ups and savings noise are folded into one row per statement (a lump). |
| D7 | Categories are MoneyWiz's job: the CSV has none, and Advanced import assigns them per payee and remembers. |
| D8 | Only the owner's own name, phone or a bank's own-account marker makes a row an own transfer. Money from or to anyone else is income or expense. |
| D9 | Every exported row carries a stable tag in its Memo, so `verify` matches exactly. |
| D10 | How MoneyWiz treats imported transfers is measured once by `probe`, not assumed. |
| D11 | `convert` does not filter rows already in MoneyWiz: the import dialog handles duplicates, and `verify` reports what slips through. |

## Stack

Python 3.14, uv (`uv_build`, src layout). Typer and Rich for the CLI, pydantic for config, frozen
slotted dataclasses for pipeline records, `Decimal` for money. openpyxl and xlrd for spreadsheets,
stdlib for CSV, OFX (XML), TOML and SQLite. No pandas (floats). pytest, with ruff and ty (every
rule at error) run as tests.

## Pipeline

```
folder ─ Discover ─▶ files matched to accounts
       ─ Parse ────▶ StatementRow per input row, raw fields verbatim
       ─ Classify ─▶ ClassifiedRow: kind, counterpart, evidence
       ─ Lump ─────▶ lumps; rows an imported lump already covers are skipped
       ─ Link ─────▶ transfer pairs, single legs, unmatched
       ─ Export ───▶ moneywiz_import.csv + report
verify ─ same pipeline, then match against MoneyWiz ─▶ diff report
```

Each stage takes the previous stage's records and returns new ones with an evidence note. No stage
drops a row without a named reason.

### Discover

Only `*.csv`, `*.ofx`, `*.xlsx`, `*.xls`. Bank and kind come from content (CSV header, sheet
layout, OFX signature), never the file name. The account comes from config: an in-file id first
(TBank `ACCTID` per `STMTRS` block, Santander IBAN), else the `file` glob. No match or several
matches is an error. An unrecognised statement-type file is reported, never silently skipped.

### Parse

One `StatementRow` per input row: date (and whether it has a time), amount net of fee, currency,
description, counterparty name and account, bank type and category, state (settled, pending,
reverted), external id, running balance. Reverted and pending rows are kept and tagged. A format
violation raises `StatementFormatError(file, row, column, expected, found)`.

### Classify

Per row, no cross-row context. The first rule that applies wins:

1. Reverted rows are excluded.
2. Savings-statement rows by their type: interest, fee, or excluded as internal or mirrored.
3. Pocket rows: a move to a mapped pocket, pocket interest, or excluded (`hidden_pocket`,
   `pocket_side_row`).
4. Cash rows become `cash` transfers when `[cash]` is configured.
5. The bank's rules: `own_transfer` (owner name or phone, or an own-account marker; the evidence
   may limit which accounts the other leg can be in, and may require that leg to be found,
   `pair_only`), `third_party`, then `purchase`, `refund`, `fee`, `interest`, `cashback`,
   `income` from the bank's own type, with a sign-based fallback.

### Lump

Round-ups (pocket moves up to `roundup_max`) per pocket, interest into pockets or on a savings
statement, and savings fees become one row per statement, dated its last row. The lump's Memo
carries `smt-lump:<key>:<cutoff>`: the key hashes bank, account, kind, pocket and target account;
the cut-off is the last row's timestamp. Rows at or before the newest cut-off MoneyWiz holds
for the same key are skipped (`covered_by_lump`).

### Link

Candidates pair across different accounts with opposite signs within `window_days`, when each
leg's evidence allows the other's account. Same currency: amounts within `tolerance`.
Cross-currency: no amount test, but both legs need evidence naming the other account.

Ranking: same-currency pairs first, then the smallest effective gap (exact for timed legs, whole
days plus 12 hours when a leg has a date only), then the smallest amount difference. Ties pair in
a content-based order, independent of file order, and are noted.

Unpaired: exactly one possible account gives a single-leg transfer to it; otherwise the row is
exported with payee `Unmatched transfer`. `pair_only` evidence never makes a single leg.

### Export

CSV in UTF-8 with columns `Date, Amount, Payee, Description, Account, Transfers, Memo`. Date
`yyyy-MM-dd`, signed amount in the account's currency, dot decimal. `Transfers` names the other
account exactly as MoneyWiz does. A pair exports its outgoing leg only; MoneyWiz creates the
other.

Memo `smt:<tag>`: a short hash of bank, account and external id (or date, amount, description),
plus an ordinal among identical rows of one file, so a tag never depends on what else is
exported. A paired transfer carries both legs' tags.

### Invariants

- Row accounting: every input row is exactly one of `exported`, `merged` (into a lump or pair),
  `skipped` (covered by a lump) or `excluded` (named reason); the four sum to the input count per
  file.
- Balance: for a statement with a running balance, the sum of non-reverted amounts equals closing
  minus opening balance. Checked at Parse; a mismatch blocks the write.

## Verify

Runs the pipeline with lump coverage, then matches each export unit (row, transfer, lump):

1. By tag in the MoneyWiz transaction's notes.
2. Otherwise, one to one among untagged MoneyWiz rows: same account, equal signed amount, dates
   within a window. Three passes: transfer legs against MoneyWiz transfers to the expected account
   (`window_days`), plain rows against plain rows (1 day), then the rest (1 day). Within a pass a
   MoneyWiz row goes to the candidate whose window closes first.

A transfer is present when either leg is found. Lumps match by tag only. Extra rows are untagged
MoneyWiz rows in the statement's period that nothing matched; lump rows and reconcile rows are
never extra. A balance agrees when the difference is zero or explained by pending, missing and
extra rows up to that day.

## MoneyWiz

- The reader copies the SQLite store with its `-wal` and `-shm` to a temp dir and opens it
  read-only; it refuses while MoneyWiz runs. Reading the container needs Full Disk Access.
- Store: `~/Library/Containers/<app id>/Data/Library/Application Support/MoneyWiz_iCloud.sqlite`;
  the default is the Setapp edition, overridable in config. Schema notes:
  [moneywiz-schema.md](moneywiz-schema.md).
- Behaviour measured with `probe`, recorded in `smoothment.probe.toml` next to the config:
  - the Memo lands in the transaction's notes, so tags are readable after import;
  - one imported transfer leg is enough, MoneyWiz creates the other side;
  - two imported legs also link into one transfer;
  - a leg whose other side was entered by hand before the import is duplicated, not linked;
  - a cross-currency single leg gets MoneyWiz's own rate on the other side, so the received amount
    is set by hand and checked by `verify`.
- The CSV import drops the time of day and rows with a zero amount; `convert` leaves the latter
  out.

## Testing

- Synthetic fixtures only; one test module per parser, table-driven classify and link tests, a
  must-not-pair case for every wrong pairing seen.
- Row accounting and balance checks asserted on every fixture.
- A local replay test runs `convert --dry-run` over real monthly folders; skipped unless
  `SMOOTHMENT_REPLAY` is set.

## Not built

- Payee matching to existing MoneyWiz payees (exact after normalisation, then config synonyms).
  Today payees are exported as the bank states them, and MoneyWiz's import links them.
- Filtering the CSV against MoneyWiz (`--skip-existing`), if the import dialog proves unreliable.
- More banks (IdBank first).

## Out of scope

Bank APIs, a GUI, writing into MoneyWiz, OFX export, other target apps.
