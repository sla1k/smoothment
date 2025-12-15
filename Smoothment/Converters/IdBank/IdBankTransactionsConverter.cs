using System.Globalization;
using Smoothment.Extensions;
using ClosedXML.Excel;
using Microsoft.Extensions.Logging;

namespace Smoothment.Converters.IdBank;

public class IdSmoothment(ILogger<IdSmoothment> logger) : ITransactionsConverter
{
    private const string HeaderMarker = "Document number";
    private const string EndMarker = "Balance at the end";

    private const int DocumentNumberColumn = 1; // Column A - Document number
    private const int DateColumn = 3; // Column C - Date
    private const int DebitColumn = 4; // Column D - Debit amount
    private const int CreditColumn = 5; // Column E - Credit amount
    private const int AdditionalInfoColumn = 6; // Column F - Additional info
    private const int AccountColumn = 7; // Column G - Account
    private const int PayeeColumn = 8; // Column H - Payee
    private const int DescriptionColumn = 9; // Column I - Description
    public string Key => "idbank";

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
        var dataStartRow = FindDataStartRow(worksheet, lastRow);

        if (dataStartRow == 0)
        {
            logger.LogWarning("Could not find the start of the transactions in the file");
            return Task.FromResult<IReadOnlyCollection<Transaction>>(transactions);
        }

        for (var row = dataStartRow; row <= lastRow; row++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var firstCellValue = worksheet.Cell(row, DocumentNumberColumn).GetString();
            if (firstCellValue.Contains(EndMarker, StringComparison.OrdinalIgnoreCase)) break;

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

    private static int FindDataStartRow(IXLWorksheet worksheet, int lastRow)
    {
        for (var row = 1; row <= lastRow; row++)
        {
            var cellValue = worksheet.Cell(row, DocumentNumberColumn).GetString().NormalizeWhitespace();
            if (cellValue.Contains(HeaderMarker, StringComparison.InvariantCultureIgnoreCase)) return row + 1;
        }

        return 0;
    }

    private Transaction? ParseRow(IXLWorksheet worksheet, int row, string account)
    {
        var dateText = worksheet.Cell(row, DateColumn).GetString()?.Trim();

        if (string.IsNullOrWhiteSpace(dateText)) return null;

        // IdBank uses format: dd/MM/yyyy HH:mm:ss
        if (!DateTime.TryParseExact(
                dateText,
                "dd/MM/yyyy HH:mm:ss",
                CultureInfo.InvariantCulture,
                DateTimeStyles.None,
                out var parsedDate))
            return null;

        var date = new DateTimeOffset(parsedDate, TimeSpan.FromHours(4)); // Armenia timezone (UTC+4)

        var debitText = worksheet.Cell(row, DebitColumn).GetString()?.Trim();
        var creditText = worksheet.Cell(row, CreditColumn).GetString()?.Trim();

        var debit = decimal.TryParse(
            debitText,
            NumberStyles.Any,
            CultureInfo.InvariantCulture,
            out var parsedDebit)
            ? parsedDebit
            : 0m;

        var credit = decimal.TryParse(
            creditText,
            NumberStyles.Any,
            CultureInfo.InvariantCulture,
            out var parsedCredit)
            ? parsedCredit
            : 0m;

        // Debit is expense (negative), credit is income (positive)
        var amount = debit > 0 ? -debit : credit;

        var payee = worksheet.Cell(row, PayeeColumn).GetString().NormalizeWhitespace();

        if (string.IsNullOrWhiteSpace(payee)) return null;

        var description = worksheet.Cell(row, DescriptionColumn).GetString().NormalizeWhitespace();
        var additionalInfo = worksheet.Cell(row, AdditionalInfoColumn).GetString()?.Trim();

        if (!string.IsNullOrWhiteSpace(additionalInfo))
            description = string.IsNullOrWhiteSpace(description)
                ? additionalInfo
                : $"{description} {additionalInfo}";

        var transactionAccount = worksheet.Cell(row, AccountColumn).GetString()?.Trim();
        if (string.IsNullOrWhiteSpace(transactionAccount)) transactionAccount = account;

        var transaction = new Transaction
        {
            Bank = Key,
            Account = transactionAccount,
            Payee = payee,
            Amount = amount,
            Category = null,
            Description = description,
            Date = date,
            Currency = "AMD",
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
