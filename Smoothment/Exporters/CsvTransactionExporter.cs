using System.Globalization;
using Smoothment.Converters;
using CsvHelper;

namespace Smoothment.Exporters;

/// <summary>
///     CSV transaction exporter
/// </summary>
public class CsvTransactionExporter : ITransactionExporter
{
    public string Key => "csv";
    public string FileExtension => ".csv";

    public async Task ExportAsync(IReadOnlyCollection<Transaction> transactions, string outputPath,
        CancellationToken cancellationToken)
    {
        await using var writer = new StreamWriter(outputPath);
        await using var csv = new CsvWriter(writer, CultureInfo.InvariantCulture);
        await csv.WriteRecordsAsync(transactions, cancellationToken);
    }
}
