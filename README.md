# Smoothment

A .NET CLI tool that normalizes raw bank statements from multiple institutions and exports them to CSV or OFX so they can be imported into budgeting apps without manual editing.

## Why "Smoothment"?

**Smoothment** = Smooth + Statement

Like a smoothie blends different fruits into one delicious drink, Smoothment blends your bank statements from different institutions into one smooth, unified format. No more manual reformatting - just smooth, consistent transaction data ready for your budgeting app.

## Why I Built This

Living as an immigrant, I've accumulated bank accounts and cards in Armenia, Turkey, Spain, and Belgium over the years. Managing transactions from all these different banks became overwhelming - each bank exports data in its own format (CSV, Excel, different column layouts), and none of them support OFX export that my budget app could import directly. Every month, I'd spend hours manually copying and reformatting transactions.

This tool automates that tedious process — it takes exports from all my banks, normalizes them into a single format, and enriches them with categories and payee information. Now what used to take hours takes seconds.

## Features

- Convert transactions from any supported bank in a single run (mix CSV and XLSX inputs).
- Enrich payees/categories via a local SQLite database so exports match your budgeting taxonomy.
- Export to CSV or OFX, preserving transfer hints and currency per account.
- Plugin-based converters and exporters auto-registered through Scrutor; adding a new bank is just a new class with a unique key.

## Supported Banks

| Bank | Key | File Format |
|------|-----|-------------|
| TBank (Tinkoff) | `tbank` | CSV / OFX |
| Revolut | `revolut` | CSV |
| Wise (TransferWise) | `wise` | CSV |
| IdBank | `idbank` | Excel (.xlsx) |
| BBVA | `bbva` | Excel (.xlsx) |
| Santander | `santander` | Excel (.xlsx) |

The command line expects the lowercase key in every `--file` argument.

## Prerequisites

- .NET 10 SDK (pinned via `global.json`).
- SQLite is bundled with .NET, no external server required.

## Installation

Install as a global .NET tool:

```bash
dotnet tool install --global Smoothment
```

Or build from source:

```bash
git clone https://github.com/sla1k/smoothment.git
cd smoothment
dotnet pack -c Release
dotnet tool install --global --add-source ./Smoothment/bin/Release Smoothment
```

The first run will create a `smoothment.db` SQLite file next to the executable. It stores payees and categories that drive enrichment.

## Usage

### Converting Transactions

```bash
smoothment convert \
  --file=./tbank.csv:tbank:savings \
  --file=./revolut.csv:revolut:main \
  --output=./exports/all.csv \
  --format=csv
```

#### Convert Options

| Option | Required | Description |
|--------|----------|-------------|
| `--file=<path>:<bank>:<account>` | ✅ | Input file path, bank key, and account label. Repeatable. |
| `--output=<path>` | ❌ | Output file path. Defaults to `./converted_transactions.{csv\|ofx}`. |
| `--format=<csv\|ofx>` | ❌ | Export format. Defaults to `csv`. |

#### Examples

```bash
# Convert one file to CSV
smoothment convert \
  --file=./downloads/tbank_export.csv:tbank:checking \
  --output=./exports/tbank.csv

# Merge multiple banks and emit OFX
smoothment convert \
  --file=./tbank.csv:tbank:savings \
  --file=./revolut.csv:revolut:main \
  --file=./wise.csv:wise:eur \
  --format=ofx \
  --output=./exports/all_accounts.ofx
```

### Managing Categories

```bash
# List all categories
smoothment category

# Add a new category
smoothment category add "Groceries"

# Remove a category
smoothment category remove "Groceries"

# Add a synonym to a category
smoothment category synonym "Groceries" "supermarket"
```

### Managing Payees

```bash
# List all payees
smoothment payee

# Add a new payee
smoothment payee add "Starbucks"

# Add a payee with expense/top-up metadata
smoothment payee add "Starbucks" \
  --expense-category="Coffee" \
  --expense-description="Coffee shop" \
  --topup-category="Refund" \
  --topup-description="Refund from coffee shop"

# Remove a payee
smoothment payee remove "Starbucks"

# Add a synonym to a payee
smoothment payee synonym "Starbucks" "STARBUCKS CORP"
```

### Command Reference

| Command | Description |
|---------|-------------|
| `smoothment convert` | Convert bank statements to unified format |
| `smoothment category` | List all categories |
| `smoothment category add <name>` | Add a new category |
| `smoothment category remove <name>` | Remove a category |
| `smoothment category synonym <name> <synonym>` | Add a synonym to a category |
| `smoothment payee` | List all payees |
| `smoothment payee add <name> [options]` | Add a new payee |
| `smoothment payee remove <name>` | Remove a payee |
| `smoothment payee synonym <name> <synonym>` | Add a synonym to a payee |

#### Payee Add Options

| Option | Description |
|--------|-------------|
| `--expense-category` | Category for expense transactions |
| `--expense-description` | Description for expense transactions |
| `--topup-category` | Category for top-up transactions |
| `--topup-description` | Description for top-up transactions |

## Output Formats

### CSV

Every row represents a normalized transaction with the columns below:

| Column | Description |
|--------|-------------|
| Bank | Source bank key |
| Account | Account label provided on the CLI |
| Payee | Merchant/payee after enrichment |
| Amount | Signed amount (negative = expense) |
| Category | Enriched or original category |
| Description | Converter/enricher notes |
| Date | ISO 8601 timestamp |
| Currency | ISO 4217 currency code |
| IsTransfer | `true` when the converter detected an internal transfer |

### OFX

`OfxTransactionExporter` writes OFX 1.0.2 (SGML) output with transaction groups split by bank, account, and currency. Every transaction receives a deterministic FITID based on its attributes so duplicate imports can be detected by receiving apps.

## Database Enrichment

Converters emit raw transactions, then `TransactionEnricher` loads payees and categories from the SQLite database to normalize the final output.

- Database file: `smoothment.db` (created next to the CLI executable).
- Tables: `Payees` hold canonical names plus per-type descriptions/categories; `Categories` provide synonym normalization.
- Reset or edit via your favorite SQLite browser. For a clean slate you can run `scripts/reset_migrations.sql` in sqlite3.

### Migrations

```bash
dotnet ef migrations add <MigrationName> --project Smoothment
dotnet ef database update --project Smoothment
```

## Testing

The solution contains `Smoothment` (CLI) and `Smoothment.Tests` (xUnit). Tests mirror the production folder layout:

- Converter tests live under `Smoothment.Tests/Converters/<BankName>/` and rely on anonymized fixtures committed to the repo.
- Exporter and service tests verify CSV/OFX serialization and enrichment behavior.

Run everything with:

```bash
dotnet test
```

## Development & Extensibility

- .NET configuration comes from `global.json`, and `.editorconfig` enforces code style (file-scoped namespaces, 4 spaces, etc.).
- `Program.cs` wires System.CommandLine → DI; converters/exporters are discovered via Scrutor and exposed through factory delegates (`Func<string, ITransactionsConverter>` / `Func<string, ITransactionExporter>`). Register a new converter by adding a class under `Converters/<BankName>/` that implements `ITransactionsConverter` and exposes a unique lowercase `Key`.
- Add exporters under `Exporters/` with their own `Key` and `FileExtension`. Remember to extend the `--format` option in `ConvertCommand`.
- Services are orchestrated from `TransactionProcessingService` which streams files sequentially and hands the combined set to `TransactionEnricher`.

## License

MIT License - see [LICENSE](LICENSE) for details.
