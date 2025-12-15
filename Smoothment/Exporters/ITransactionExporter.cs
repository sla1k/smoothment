using Smoothment.Converters;

namespace Smoothment.Exporters;

/// <summary>
///     Transaction exporter interface
/// </summary>
public interface ITransactionExporter
{
    /// <summary>
    ///     Export format key (e.g., "csv", "ofx")
    /// </summary>
    string Key { get; }

    /// <summary>
    ///     File extension for this format (e.g., ".csv", ".ofx")
    /// </summary>
    string FileExtension { get; }

    /// <summary>
    ///     Export transactions to a file
    /// </summary>
    /// <param name="transactions">Transactions to export</param>
    /// <param name="outputPath">Output file path</param>
    /// <param name="cancellationToken">Cancellation token</param>
    Task ExportAsync(IReadOnlyCollection<Transaction> transactions, string outputPath,
        CancellationToken cancellationToken);
}
