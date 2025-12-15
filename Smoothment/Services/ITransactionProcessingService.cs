using Smoothment.Converters;
using Smoothment.Models;

namespace Smoothment.Services;

public interface ITransactionProcessingService
{
    Task<IReadOnlyCollection<Transaction>> ProcessFilesAsync(
        IEnumerable<BankStatementFile> files,
        CancellationToken cancellationToken);
}
