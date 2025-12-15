using Smoothment.Converters;

namespace Smoothment.Services;

public interface ITransactionEnricher
{
    Task<IReadOnlyCollection<Transaction>> EnrichAsync(
        IReadOnlyCollection<Transaction> transactions,
        CancellationToken cancellationToken);
}
