using System.Globalization;
using Smoothment.Extensions;
using CsvHelper;
using CsvHelper.Configuration;

namespace Smoothment.Converters.Wise;

public class WiseTransactionsConverter : ITransactionsConverter
{
    public string Key => "wise";

    public async Task<IReadOnlyCollection<Transaction>> ConvertAsync(Stream fileStream, string account,
        CancellationToken cancellationToken)
    {
        using var reader = new StreamReader(fileStream);
        using var csv = new CsvReader(reader, new CsvConfiguration(CultureInfo.InvariantCulture)
        {
            Delimiter = ",",
            HasHeaderRecord = true,
            BadDataFound = context =>
                throw new InvalidDataException($"Неверный формат данных в строке {context.RawRecord}")
        });
        csv.Context.RegisterClassMap<WiseTransactionRecordMap>();
        csv.Context.TypeConverterOptionsCache.GetOptions<DateTimeOffset>().Formats = ["dd-MM-yyyy HH:mm:ss.fff"];
        var transactions = new List<Transaction>();

        await foreach (var record in csv.GetRecordsAsync<WiseTransactionRecord>(cancellationToken))
        {
            var transaction = new Transaction
            {
                Bank = Key,
                Account = account,
                Date = record.Date,
                Amount = record.Amount,
                Currency = record.Currency,
                Payee = record.Payee.RemoveLastWord(),
                Description = record.Description,
                Category = null,
                IsTransfer = record.TransferWiseId?.StartsWith("TRANSFER-", StringComparison.OrdinalIgnoreCase) ?? false
            };

            transactions.Add(transaction);
        }

        return transactions;
    }
}

internal record WiseTransactionRecord
{
    public required string? TransferWiseId { get; init; }
    public required DateTimeOffset Date { get; init; }
    public required decimal Amount { get; init; }
    public required string Currency { get; init; }
    public required string Description { get; init; }
    public required string Payee { get; init; }
}

internal sealed class WiseTransactionRecordMap : ClassMap<WiseTransactionRecord>
{
    public WiseTransactionRecordMap()
    {
        Map(m => m.TransferWiseId).Name("TransferWise ID");
        Map(m => m.Date).Name("Date Time");
        Map(m => m.Amount).Name("Amount");
        Map(m => m.Currency).Name("Currency");
        Map(m => m.Description).Name("Description");
        Map(m => m.Payee).Name("Merchant");
    }
}
