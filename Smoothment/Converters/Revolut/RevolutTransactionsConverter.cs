using System.Globalization;
using CsvHelper;
using CsvHelper.Configuration;

namespace Smoothment.Converters.Revolut;

public class RevolutTransactionsConverter : ITransactionsConverter
{
    public string Key => "revolut";

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
        csv.Context.RegisterClassMap<RevolutTransactionRecordMap>();
        var transactions = new List<Transaction>();

        await foreach (var record in csv.GetRecordsAsync<RevolutTransactionRecord>(cancellationToken))
        {
            var transaction = new Transaction
            {
                Bank = Key,
                Account = account,
                Date = record.Date,
                Amount = record.Amount,
                Currency = record.Currency,
                Payee = record.Payee,
                Category = null,
                Description = null,
                IsTransfer = record.Type?.Equals("TRANSFER", StringComparison.OrdinalIgnoreCase) ?? false
            };

            transactions.Add(transaction);
        }

        return transactions;
    }
}

internal record RevolutTransactionRecord
{
    public required string? Type { get; init; }
    public required DateTimeOffset Date { get; init; }
    public required decimal Amount { get; init; }
    public required string Currency { get; init; }
    public required string Payee { get; init; }
}

internal sealed class RevolutTransactionRecordMap : ClassMap<RevolutTransactionRecord>
{
    public RevolutTransactionRecordMap()
    {
        Map(m => m.Type).Name("Type");
        Map(m => m.Date).Name("Started Date");
        Map(m => m.Amount).Name("Amount");
        Map(m => m.Currency).Name("Currency");
        Map(m => m.Payee).Name("Description");
    }
}
