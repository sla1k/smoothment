using System.CommandLine;
using System.CommandLine.Parsing;
using Smoothment.Models;
using Microsoft.Extensions.DependencyInjection;

namespace Smoothment.Commands.Convert;

public static class ConvertCommand
{
    public static Command Create(IServiceProvider serviceProvider)
    {
        var inputOption = new Option<IEnumerable<BankStatementFile>>("--file")
        {
            Description =
                """
                Bank statement file in format <path>:<bank>:<account>
                  - path: relative or absolute file path
                  - bank: revolut, wise, tbank, idbank, bbva, santander
                  - account: account name for grouping (e.g., checking, savings)

                Can be specified multiple times to merge transactions from different sources.
                Example: --file=revolut.csv:revolut:main --file=wise.csv:wise:business
                """,
            AllowMultipleArgumentsPerToken = true,
            Required = true,
            CustomParser = ParseBankStatementFiles
        };
        inputOption.Validators.Add(ValidateInputFiles);

        var outputOption = new Option<string?>("--output")
        {
            Description =
                """
                Output file path for converted transactions.
                Default: ./converted_transactions.{csv|ofx} (based on --format)
                """
        };
        outputOption.Validators.Add(ValidateOutputPath);

        var formatOption = new Option<string>("--format")
        {
            Description =
                """
                Output format:
                  - csv: Simple CSV with all transaction fields
                  - ofx: OFX 1.0.2 (SGML) for import into accounting software
                """,
            DefaultValueFactory = _ => "csv"
        };
        formatOption.AcceptOnlyFromAmong("csv", "ofx");

        var command = new Command("convert",
            """
            Convert bank transaction files into a unified format.

            Reads transaction exports from supported banks, enriches them with
            category and payee information from the local database, and outputs
            a single file containing all transactions.
            """)
        {
            inputOption,
            outputOption,
            formatOption
        };

        command.SetAction(async (parseResult, cancellationToken) =>
        {
            var inputFiles = parseResult.GetValue(inputOption)!;
            var output = parseResult.GetValue(outputOption);
            var format = parseResult.GetValue(formatOption)!.ToLowerInvariant();

            using var scope = serviceProvider.CreateScope();
            var handler = scope.ServiceProvider.GetRequiredService<ICommandHandler<ConvertCommandOptions>>();

            var options = new ConvertCommandOptions(inputFiles, output, format);
            return await handler.ExecuteAsync(options, cancellationToken);
        });

        return command;
    }

    private static IEnumerable<BankStatementFile> ParseBankStatementFiles(ArgumentResult result)
    {
        var list = new List<BankStatementFile>();
        foreach (var token in result.Tokens)
        {
            var parts = token.Value.Split(':');
            if (parts.Length != 3)
            {
                result.AddError("Each --file argument must be in the format <path>:<bank>:<account>");
                return list;
            }

            list.Add(new BankStatementFile(parts[0], parts[1], parts[2]));
        }

        return list;
    }

    private static void ValidateInputFiles(OptionResult result)
    {
        var files = result.GetValueOrDefault<IEnumerable<BankStatementFile>>();
        if (files is null) return;

        foreach (var file in files)
        {
            var currentDir = Directory.GetCurrentDirectory();
            var normalizedPath = Path.IsPathFullyQualified(file.FilePath)
                ? Path.GetFullPath(file.FilePath)
                : Path.GetFullPath(Path.Combine(currentDir, file.FilePath));

            if (!Path.IsPathFullyQualified(file.FilePath) &&
                !normalizedPath.StartsWith(currentDir, StringComparison.OrdinalIgnoreCase))
            {
                result.AddError("Path traversal is not allowed.");
                return;
            }

            if (string.IsNullOrWhiteSpace(file.Bank))
            {
                result.AddError("The bank parameter is required.");
                return;
            }
        }
    }

    private static void ValidateOutputPath(OptionResult result)
    {
        var outputPath = result.GetValueOrDefault<string>();
        if (string.IsNullOrEmpty(outputPath)) return;

        var currentDir = Directory.GetCurrentDirectory();
        var normalizedPath = Path.IsPathFullyQualified(outputPath)
            ? Path.GetFullPath(outputPath)
            : Path.GetFullPath(Path.Combine(currentDir, outputPath));

        if (!Path.IsPathFullyQualified(outputPath) &&
            !normalizedPath.StartsWith(currentDir, StringComparison.OrdinalIgnoreCase))
            result.AddError("Path traversal is not allowed.");
    }
}
