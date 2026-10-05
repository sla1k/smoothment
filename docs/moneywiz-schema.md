# MoneyWiz SQLite schema

The live store is
`~/Library/Containers/<app id>/Data/Library/Application Support/MoneyWiz_iCloud.sqlite`. A "Data
Backup" zip's `ipadMoneyWiz.sqlite` has the same schema; the older `.AppData/ipadMoneyWiz.sqlite`
path holds only a stale migration copy.

## Layout

Core Data single-table inheritance: all entities live in `ZSYNCOBJECT`, discriminated by
`Z_ENT`. The entity map is in `Z_PRIMARYKEY` (`SELECT Z_ENT, Z_NAME FROM Z_PRIMARYKEY`).

| Entity | Z_ENT | Name column | Other relevant columns |
|--------|-------|-------------|------------------------|
| Account (all types) | 10–17 | `ZNAME` | `ZCURRENCYNAME` (currency code) |
| Category | 20 | `ZNAME2` | `ZPARENTCATEGORY` (→ `Z_PK`, hierarchy), `ZTYPE2` (1 = expense, 2 = income), `ZUSER3` (owner user) |
| Payee | 29 | `ZNAME5` | `ZUSER7` (owner user), `ZIMPORTLINKIDARRAY2` (NSKeyedArchiver bplist of import-mapping strings — ignore) |
| Transaction (all types) | 37–48 | — | `ZPAYEE2` (→ Payee `Z_PK`) — used for payee→category rule mining |

Category assignments live in a separate table `ZCATEGORYASSIGMENT`
(`ZTRANSACTION` → transaction `Z_PK`, `ZCATEGORY` → category `Z_PK`; multiple rows per
transaction for splits). Joining transactions to assignments yields each payee's historical
category votes — sync-moneywiz stores the per-direction majority as
`MoneyWizPayees.ExpenseCategoryPath` / `IncomeCategoryPath`.

Account subtypes: 10 Account, 11 BankCheque, 12 BankSaving, 13 Cash, 14 CreditCard,
15 Loan, 16 Investment, 17 Forex.

## Data facts

- Categories belong to a user (`ZUSER3`); with several users in one store, names repeat across
  users, so pick one user's tree or merge by distinct (name, parent) pairs.
- Payees (`ZNAME5`) are per user too, via `ZUSER7`.
- Category hierarchy resolves with a self-join:
  `LEFT JOIN ZSYNCOBJECT p ON c.ZPARENTCATEGORY = p.Z_PK` → "Shopping > Accessories".
- Malformed rows exist (categories named `???`, `ZTYPE2 = 65535`); readers must tolerate them.

## Gotchas

- Always copy the `.sqlite` **and** `-wal`/`-shm` sidecars before opening (or open the copy
  read-only after a WAL checkpoint); the app must be closed for the live container file.
- Payee/category text can contain non-breaking spaces (`\xa0`) — normalize before matching.
- `ZUSER` columns are numbered per Core Data relationship, not per entity: category owner is
  `ZUSER3`, payee owner is `ZUSER7`. Do not assume the same column across entities.
