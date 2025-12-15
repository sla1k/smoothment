namespace Smoothment.Converters;

public interface ITransactionsConverter
{
    string Key { get; }

    Task<IReadOnlyCollection<Transaction>> ConvertAsync(Stream fileStream, string account,
        CancellationToken cancellationToken);
}
