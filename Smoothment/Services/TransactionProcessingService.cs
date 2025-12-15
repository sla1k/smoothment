using Smoothment.Converters;
using Smoothment.Models;

namespace Smoothment.Services;

public class TransactionProcessingService(
    Func<string, ITransactionsConverter> converterFactory,
    ITransactionEnricher enricher) : ITransactionProcessingService
{
    public async Task<IReadOnlyCollection<Transaction>> ProcessFilesAsync(
        IEnumerable<BankStatementFile> files,
        CancellationToken cancellationToken)
    {
        var transactions = new List<Transaction>();

        foreach (var file in files)
        {
            if (!File.Exists(file.FilePath))
                throw new FileNotFoundException($"Input file not found: {file.FilePath}", file.FilePath);

            var converter = converterFactory(file.Bank);
            await using var stream = File.OpenRead(file.FilePath);
            var converted = await converter.ConvertAsync(stream, file.Account, cancellationToken);
            transactions.AddRange(converted);
        }

        return await enricher.EnrichAsync(transactions, cancellationToken);
    }
}
