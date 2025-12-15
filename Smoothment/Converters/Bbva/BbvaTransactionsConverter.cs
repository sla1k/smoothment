using System.Globalization;
using Smoothment.Extensions;
using ClosedXML.Excel;
using Microsoft.Extensions.Logging;

namespace Smoothment.Converters.Bbva;

public class BbvaTransactionsConverter(ILogger<BbvaTransactionsConverter> logger) : ITransactionsConverter
{
    private const int HeaderRow = 5;
    private const int DataStartRow = 6;

    private const int EffDateColumn = 2; // Column B - Effective Date
    private const int DateColumn = 3; // Column C - Transaction Date
    private const int PayeeColumn = 4; // Column D - Item (short name)
    private const int TransactionTypeColumn = 5; // Column E - Transaction type
    private const int AmountColumn = 6; // Column F - Amount
    private const int CurrencyColumn = 7; // Column G - Foreign currency
    private const int CommentsColumn = 10; // Column J - Detailed comments
    public string Key => "bbva";

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
                Console.Error.WriteLine($"Warning: Skipping row {row} due to error: {ex.Message}");
            }
        }

        return Task.FromResult<IReadOnlyCollection<Transaction>>(transactions);
    }

    private Transaction? ParseRow(IXLWorksheet worksheet, int row, string account)
    {
        var dateText = worksheet.Cell(row, DateColumn).GetString()?.Trim();
        if (string.IsNullOrWhiteSpace(dateText)) dateText = worksheet.Cell(row, EffDateColumn).GetString()?.Trim();

        if (string.IsNullOrWhiteSpace(dateText)) return null;

        // BBVA uses US date format: MM/dd/yyyy
        if (!DateTime.TryParseExact(
                dateText,
                "MM/dd/yyyy",
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var parsedDate))
            return null;

        var date = new DateTimeOffset(parsedDate, TimeSpan.FromHours(1)); // Spain timezone (CET, UTC+1)

        var payee = worksheet.Cell(row, PayeeColumn).GetString().NormalizeWhitespace();

        if (string.IsNullOrWhiteSpace(payee)) return null;

        var amountText = worksheet.Cell(row, AmountColumn).GetString()?.Trim();
        var amount = decimal.TryParse(
            amountText,
            NumberStyles.Any,
            CultureInfo.InvariantCulture,
            out var parsedAmount)
            ? parsedAmount
            : 0m;

        var currencyText = worksheet.Cell(row, CurrencyColumn).GetString()?.Trim();
        var currency = string.IsNullOrWhiteSpace(currencyText) ? "EUR" : currencyText;

        var description = worksheet.Cell(row, CommentsColumn).GetString().NormalizeWhitespace();

        var transaction = new Transaction
        {
            Bank = Key,
            Account = account,
            Payee = payee,
            Amount = amount,
            Category = null,
            Description = description,
            Date = date,
            Currency = currency,
            IsTransfer = IsTransfer(payee)
        };

        return transaction;
    }

    private static bool IsTransfer(string? payee)
    {
        if (string.IsNullOrWhiteSpace(payee)) return false;

        return payee.Contains("transfer", StringComparison.OrdinalIgnoreCase);
    }
}
