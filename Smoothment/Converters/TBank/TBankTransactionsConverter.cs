using System.Globalization;
using System.Text;
using System.Xml.Linq;
using Smoothment.Extensions;
using CsvHelper;
using CsvHelper.Configuration;

namespace Smoothment.Converters.TBank;

public class TSmoothment : ITransactionsConverter
{
    public string Key => "tbank";

    public async Task<IReadOnlyCollection<Transaction>> ConvertAsync(Stream fileStream, string account,
        CancellationToken cancellationToken)
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

        var encoding = await fileStream.DetectEncodingAsync(cancellationToken);
        fileStream.Position = 0; // Reset stream after encoding detection

        using var reader = new StreamReader(fileStream, encoding, leaveOpen: true);

        // Peek at the first few characters to determine file format
        var buffer = new char[10];
        var charsRead = await reader.ReadAsync(buffer.AsMemory(), cancellationToken);
        fileStream.Position = 0; // Reset stream again

        var fileStart = new string(buffer, 0, charsRead);
        var isOfx = fileStart.StartsWith("<?xml", StringComparison.OrdinalIgnoreCase) ||
                    fileStart.Contains("OFX", StringComparison.OrdinalIgnoreCase);

        if (isOfx) return await ConvertFromOfxAsync(fileStream, account, cancellationToken);

        return await ConvertFromCsvAsync(fileStream, account, encoding, cancellationToken);
    }

    private async Task<IReadOnlyCollection<Transaction>> ConvertFromCsvAsync(Stream fileStream, string account,
        Encoding encoding, CancellationToken cancellationToken)
    {
        using var reader = new StreamReader(fileStream, encoding);
        using var csv = new CsvReader(reader, new CsvConfiguration(CultureInfo.GetCultureInfo("ru-RU"))
        {
            Delimiter = ";",
            HasHeaderRecord = true,
            BadDataFound = context =>
                throw new InvalidDataException($"Неверный формат данных в строке {context.RawRecord}")
        });
        csv.Context.RegisterClassMap<TBankCsvRecordMap>();
        var transactions = new List<Transaction>();

        await foreach (var record in csv.GetRecordsAsync<TBankCsvRecord>(cancellationToken))
        {
            var isTransferCategory = record.Category?.Equals("Переводы", StringComparison.InvariantCultureIgnoreCase) ??
                                     false;
            var isTransferDescription =
                record.Description?.Contains("Перевод между счетами", StringComparison.InvariantCultureIgnoreCase) ??
                false;
            var isTransfer = isTransferCategory && isTransferDescription;

            var transaction = new Transaction
            {
                Bank = Key,
                Account = account,
                Date = new DateTimeOffset(record.Date, TimeSpan.FromHours(3)), // Moscow timezone (UTC+3)
                Amount = record.Amount,
                Payee = record.Payee,
                Category = record.Category,
                Description = record.Description,
                Currency = "RUB",
                IsTransfer = isTransfer
            };

            transactions.Add(transaction);
        }

        return transactions;
    }

    private async Task<IReadOnlyCollection<Transaction>> ConvertFromOfxAsync(Stream fileStream, string account,
        CancellationToken cancellationToken)
    {
        using var reader = new StreamReader(fileStream, Encoding.UTF8);
        var content = await reader.ReadToEndAsync(cancellationToken);

        var doc = XDocument.Parse(content);
        var transactions = new List<Transaction>();

        var stmtTrnrsList = doc.Descendants("STMTTRNRS");

        foreach (var stmtTrnrs in stmtTrnrsList)
        {
            var stmtrs = stmtTrnrs.Element("STMTRS");
            if (stmtrs == null) continue;

            var bankAcctFrom = stmtrs.Element("BANKACCTFROM");
            var acctId = bankAcctFrom?.Element("ACCTID")?.Value ?? "Unknown";
            var acctType = bankAcctFrom?.Element("ACCTTYPE")?.Value ?? "Unknown";

            var defaultCurrency = stmtrs.Element("CURDEF")?.Value ?? "RUB";

            var bankTranList = stmtrs.Element("BANKTRANLIST");
            if (bankTranList == null) continue;

            var stmtTrns = bankTranList.Elements("STMTTRN");

            foreach (var stmtTrn in stmtTrns)
            {
                var trnType = stmtTrn.Element("TRNTYPE")?.Value;
                var dtPosted = stmtTrn.Element("DTPOSTED")?.Value;
                var trnAmt = stmtTrn.Element("TRNAMT")?.Value;
                var name = stmtTrn.Element("NAME")?.Value;
                var memo = stmtTrn.Element("MEMO")?.Value;
                var currency = stmtTrn.Element("CURRENCY")?.Element("CURSYM")?.Value ?? defaultCurrency;

                if (string.IsNullOrEmpty(trnAmt) || string.IsNullOrEmpty(dtPosted) || string.IsNullOrEmpty(name))
                    continue;

                // Parse date (format: 20251009120249.000[+3:MSK])
                var dateStr = dtPosted.Split('.')[0]; // Remove milliseconds and timezone
                if (!DateTime.TryParseExact(dateStr, "yyyyMMddHHmmss", CultureInfo.InvariantCulture,
                        DateTimeStyles.None, out var parsedDate))
                    continue;

                var date = new DateTimeOffset(parsedDate, TimeSpan.FromHours(3)); // Moscow timezone (UTC+3)

                if (!decimal.TryParse(trnAmt, NumberStyles.AllowDecimalPoint | NumberStyles.AllowLeadingSign,
                        CultureInfo.InvariantCulture, out var amount))
                    continue;

                var isTransferCategory = memo?.Equals("Переводы", StringComparison.InvariantCultureIgnoreCase) ?? false;
                var isTransferDescription = name.Contains("Между своими счетами", StringComparison.InvariantCultureIgnoreCase);
                var isTransfer = isTransferCategory && isTransferDescription;

                var transaction = new Transaction
                {
                    Bank = Key,
                    Account = account,
                    Date = date,
                    Amount = amount,
                    Payee = name,
                    Category = memo,
                    Description = name,
                    Currency = currency,
                    IsTransfer = isTransfer
                };

                transactions.Add(transaction);
            }
        }

        return transactions;
    }
}

internal record TBankCsvRecord
{
    public required DateTime Date { get; init; }
    public required decimal Amount { get; init; }
    public required string? Category { get; init; }
    public required string Payee { get; init; }
    public required string? Description { get; init; }
}

internal sealed class TBankCsvRecordMap : ClassMap<TBankCsvRecord>
{
    public TBankCsvRecordMap()
    {
        Map(m => m.Date).Name("Дата операции");
        Map(m => m.Amount).Name("Сумма операции");
        Map(m => m.Category).Name("Категория");
        Map(m => m.Payee).Name("Описание");
        Map(m => m.Description).Name("Описание");
    }
}
