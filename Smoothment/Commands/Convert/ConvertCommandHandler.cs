using Smoothment.Exporters;
using Smoothment.Services;

namespace Smoothment.Commands.Convert;

public class ConvertCommandHandler(
    ITransactionProcessingService processingService,
    Func<string, ITransactionExporter> exporterFactory) : ICommandHandler<ConvertCommandOptions>
{
    public async Task<int> ExecuteAsync(ConvertCommandOptions options, CancellationToken cancellationToken)
    {
        var transactions = await processingService.ProcessFilesAsync(options.InputFiles, cancellationToken);

        var exporter = exporterFactory(options.Format);
        var outputPath = options.OutputPath ?? $"./converted_transactions{exporter.FileExtension}";

        await exporter.ExportAsync(transactions, outputPath, cancellationToken);

        return 0;
    }
}
