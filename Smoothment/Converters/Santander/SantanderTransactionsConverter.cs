using System.Globalization;
using Smoothment.Extensions;
using ClosedXML.Excel;
using Microsoft.Extensions.Logging;

namespace Smoothment.Converters.Santander;

public class SantanderTransactionsConverter(ILogger<SantanderTransactionsConverter> logger) : ITransactionsConverter
{
    private const int HeaderRow = 7;
    private const int DataStartRow = 8;

    private const int DateColumn = 1; // Column A - Operation Date
    private const int ValueDateColumn = 2; // Column B - Value Date (unused)
    private const int ConceptoColumn = 3; // Column C - Concepto (Payee/Description)
    private const int AmountColumn = 4; // Column D - Amount in EUR
    private const int BalanceColumn = 5; // Column E - Balance (unused)
    public string Key => "santander";

    public Task<IReadOnlyCollection<Transaction>> ConvertAsync(
        Stream fileStream,
        string account,
        CancellationToken cancellationToken)
    {
        var transactions = new List<Transaction>();

        using var workbook = new XLWorkbook(fileStream);
        var worksheet = workbook.Worksheets.FirstOrDefault();

        if (worksheet == null) throw new InvalidDataException("Could not find the worksheet in the file.");

        var lastRow = worksheet.LastRowUsed()?.RowNumber() ?? 0;
        if (lastRow < DataStartRow) return Task.FromResult<IReadOnlyCollection<Transaction>>(transactions);

        for (var row = DataStartRow; row <= lastRow; row++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            try
            {
                var transaction = ParseRow(worksheet, row, account);
                if (transaction != null) transactions.Add(transaction);
            }
            catch (Exception ex)
            {
                logger.LogWarning(ex, "Skipping row {Row} due to error", row);
            }
        }

        return Task.FromResult<IReadOnlyCollection<Transaction>>(transactions);
    }

    private Transaction? ParseRow(IXLWorksheet worksheet, int row, string account)
    {
        var dateText = worksheet.Cell(row, DateColumn).GetString()?.Trim();

        if (string.IsNullOrWhiteSpace(dateText)) return null;

        // Santander uses DD/MM/YYYY format
        if (!DateTime.TryParseExact(
                dateText,
                "dd/MM/yyyy",
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var parsedDate))
            return null;

        var date = new DateTimeOffset(parsedDate, TimeSpan.FromHours(1)); // Spain timezone (CET, UTC+1)

        var concepto = worksheet.Cell(row, ConceptoColumn).GetString().NormalizeWhitespace();

        if (string.IsNullOrWhiteSpace(concepto)) return null;

        var amountText = worksheet.Cell(row, AmountColumn).GetString()?.Trim();
        var amount = decimal.TryParse(
            amountText,
            NumberStyles.Any,
            CultureInfo.InvariantCulture,
            out var parsedAmount)
            ? parsedAmount
            : 0m;

        var isTransfer = IsTransfer(concepto);

        var payee = isTransfer
            ? amount >= 0 ? "Transfer received" : "Transfer completed"
            : concepto;

        var transaction = new Transaction
        {
            Bank = Key,
            Account = account,
            Payee = payee,
            Amount = amount,
            Category = null,
            Description = concepto,
            Date = date,
            Currency = "EUR",
            IsTransfer = isTransfer
        };

        return transaction;
    }

    private static bool IsTransfer(string? concepto)
    {
        if (string.IsNullOrWhiteSpace(concepto)) return false;

        return concepto.Contains("transferencia", StringComparison.OrdinalIgnoreCase);
    }
}
