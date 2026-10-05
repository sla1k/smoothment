# Reference

## Commands

| Command | Does |
|---|---|
| `smoothment convert <folder>` | Writes `<folder>/moneywiz_import.csv` and prints a report |
| `smoothment verify <folder>` | Compares the folder with MoneyWiz after the import; writes nothing |
| `smoothment probe write` / `probe check` | One-time test of how MoneyWiz imports transfers ([below](#probe)) |

| Option | Commands | Effect |
|---|---|---|
| `--config <path>` | all | Config file. Default: `smoothment.toml` next to the statement folder (`probe`: in the current directory) |
| `--allow-running` | all | Read the MoneyWiz database while MoneyWiz is open |
| `--dry-run` | convert | Report only, write nothing |
| `--output <path>` | convert | Write the CSV elsewhere |
| `--allow-balance-mismatch` | convert | Write even when a running balance does not reconcile |
| `--no-moneywiz` | convert | Skip the database: lumps may repeat, account names go unchecked |

`convert` reads MoneyWiz only to skip rows an earlier lump covers and to check that every account
name exists (otherwise the import would create it).

## `convert` report

| Section | Shows |
|---|---|
| Unmatched transfers | Own transfers with no other leg found; see [Unmatched transfers](#unmatched-transfers) |
| Statements | Per file: account, rows, exported, merged, excluded, balance check |
| Excluded | Count per [reason](#exclusion-reasons), and skipped or unrecognised files |
| Transfers | Date, accounts, amount, legs (`2`, `1` or `lump of N`), note |
| Cross-currency transfers | Sent and received amounts. Set the received one by hand in MoneyWiz |
| Lumps | Kind, account, amount, rows, date range |

A running balance that does not reconcile blocks the write and names the first broken row; pending
rows in that file are listed as the likely cause.

### Exclusion reasons

| Reason | Row |
|---|---|
| `hidden_pocket` | Move to a pocket mapped to `"hidden"` or not mapped |
| `pocket_side_row` | The pocket's own copy of a move already on the account |
| `reverted` | Revolut row in `REVERTED` state |
| `mirrored_by_main_export` | Revolut savings `BUY` / `SELL`, already in the current-account export |
| `savings_internal` | Revolut savings reinvestment or withdrawal of returns |
| `internal_credit_repayment` | Sovcombank loan repayment |
| `duplicate_of_other_file` | Same row in two files of the folder |
| `zero_amount` | Zero amount (MoneyWiz would drop it) |

## `verify` report

Rows are found in MoneyWiz by their `smt:` tag, otherwise by account, amount and date (±1 day).

| Section | Lists |
|---|---|
| Warning | A statement that does not add up on its own; the rest may be off |
| Missing in MoneyWiz | Statement rows MoneyWiz lacks |
| Wrong in MoneyWiz | Transfers stored as plain rows or to the wrong account; wrong received amounts |
| Extra in MoneyWiz | Rows in the statement's period no statement row matches: hand entries, duplicates |
| Balances | Closing balance vs MoneyWiz on the same day, with `Pending`, `Missing`, `Extra` explaining the `Difference` |

Balance status: `ok`, `explained`, `explained by pending rows`, `unexplained <amount>`, or
`no balance in the statement`. With nothing to report it prints `Nothing to fix`.

## Rules

**Own transfers.** A row is a transfer between your accounts only when the statement shows it is
yours: one of `owner.names` (every word, any order and case), one of `owner.phones`, or a bank
marker ([per bank](supported-banks.md)). Anything else is a payment to someone else. The other
leg must be in another of your statements: opposite sign, within `transfers.window_days`, and for
the same currency within `transfers.tolerance`. The CSV keeps the outgoing amount; MoneyWiz
creates the incoming leg.

**Pockets.** Map each Revolut pocket to a MoneyWiz account; moves to a `"hidden"` or unmapped
pocket are dropped.

**Lumps.** One row per statement for each of: round-ups (pocket moves up to
`pockets.roundup_max`), interest paid into pockets or on a `savings` statement, and fees on a
`savings` statement. The lump's Memo marks where it ends, so next month's lump starts after it.

**Cash.** With `[cash]`, ATM and cash rows become transfers to that account; without it, purchases.

**Bank payee.** Fees, interest and cashback get `[banks.<bank>] payee` as payee.

### Unmatched transfers

Exported with payee `Unmatched transfer` and no other account. To fix:

- download the missing or longer statement into the folder and run `convert` again;
- or, if the other side is an account you don't track, fix it in MoneyWiz after the import;
- or, if the legs are just far apart, raise `transfers.window_days` or `transfers.tolerance`.

## Config file

Unknown keys are errors. Money and ratios are strings.

```toml
[owner]                              # required
names = ["Sample Owner", "Сэмпл О."] # every spelling on your statements
phones = ["0070000000000"]           # for phone (SBP) transfers, at least 10 digits

[[accounts]]                         # one per statement account
bank = "revolut"                     # see supported-banks.md
kind = "current"                     # current (default) or savings
moneywiz = "Shared"                  # MoneyWiz account name, exact
file = "revolut_shared*"             # or acct_id / iban; at least one

[pockets]
roundup_max = "1.00"                 # largest move counted as a round-up

[pockets.accounts.Shared]            # pockets of the account "Shared"
Travel = "Travel"                    # pocket = MoneyWiz account
Untracked = "hidden"

[banks.revolut]
payee = "Revolut"                    # payee for the bank's fees, interest, cashback

[cash]
account = "Cash"

[transfers]
window_days = 3                      # default
tolerance = "0.02"                   # default, 2% of the larger leg

[moneywiz]
db = "~/path/to/MoneyWiz_iCloud.sqlite"   # default: the Setapp edition's database
```

`[categories]` is accepted and ignored: MoneyWiz assigns categories during the import.

## Exit codes

| Code | `convert` | `verify` |
|---|---|---|
| `0` | CSV written (or would be, with `--dry-run`) | Nothing to fix |
| `1` | Balance mismatch blocked the write, or a file's row counts do not add up | Something to fix |
| `2` | Could not run: config error, a file no `[[accounts]]` entry matches, a malformed statement, MoneyWiz open, an unknown account name | Same |

## MoneyWiz import limits

- Every imported row lands at 12:00 AM; the time of day is lost.
- The first round-up lump after hand-booked round-ups counts the overlap twice; `verify` shows it
  as a balance difference. Lower the lump by that amount.
- Unwanted payees from an import: Settings > Payees merges or deletes them in bulk.

## Probe

A one-time test of how MoneyWiz handles imported transfers. `convert` doesn't need it; rerun only
after a MoneyWiz update.

```bash
uv run smoothment probe write   # writes a test CSV and prints the steps
uv run smoothment probe check   # reads the result into smoothment.probe.toml
```

If it reports `single_leg_creates_reciprocal = false`, MoneyWiz no longer creates the incoming
leg of transfers, and destination balances need fixing by hand.
