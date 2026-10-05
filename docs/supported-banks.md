# Supported banks

Each statement needs an `[[accounts]]` entry with this `bank` and `kind`, and the key it is matched
by. Without a running balance, `verify` cannot check the account's balance.

| Bank | `bank` | `kind` | File | Matched by | Running balance |
|---|---|---|---|---|---|
| [Revolut current account](#revolut) | `revolut` | `current` | CSV | `file` | Yes, per pocket |
| [Revolut savings](#revolut) | `revolut` | `savings` | CSV | `file` | No |
| [Wise](#wise) | `wise` | `current` | CSV | `file` | Yes |
| [TBank](#tbank) | `tbank` | `current` | OFX | `acct_id` | No |
| [BBVA](#bbva) | `bbva` | `current` | XLSX | `file` | Yes |
| [Santander](#santander) | `santander` | `current` | XLSX | `iban` | Yes |
| [Sovcombank](#sovcombank) | `sovcombank` | `current` | XLS | `file` | No |

`kind` is the statement format, not the account type: a TBank savings account is `current`.

## Revolut

- The current-account export includes every pocket; map them in `[pockets.accounts]`.
- The separate pocket export is ignored (its rows are already in the main one).
- Each row's fee is subtracted from its amount. Pending rows are exported; reverted ones are not.
- Savings: interest and fees become one lump per statement; buys, sells and reinvestments are
  dropped.

## Wise

- One file per currency balance, each with its own `[[accounts]]` entry.
- A top-up (`MONEY_ADDED`) is a transfer only if its other leg is found.
- A transfer to an account number matching your `iban` / `acct_id` goes to that account.

## TBank

- One OFX can hold several accounts; each gets an entry with its `acct_id`.
- Own-transfer markers: `Между своими счетами` (between TBank accounts), `Себе в другой банк`
  (to your account at another bank).
- Interest is not lumped.

## BBVA

- English and Spanish exports both work. Dates only, no times.
- `Sent from Revolut` counts as a transfer only if the Revolut leg is found.
- Cash withdrawals and deposits go to `[cash]` when configured.

## Santander

- EUR only, dates only. The IBAN is read from the file.
- A transfer in your name with reference `Sent From Revolut` is paired with your Revolut accounts.

## Sovcombank

- RUB only. Phone (SBP) transfers count as yours only when one of `owner.phones` appears.
- Loan repayments are dropped.

## Not supported yet

IdBank (planned). Any other bank needs a parser: add it under `src/smoothment/statement/parsers/`
and register it in `PARSERS`, `statement/discover.py`, the `Bank` type in `config.py` and
`classify/banks.py`, with synthetic tests.
