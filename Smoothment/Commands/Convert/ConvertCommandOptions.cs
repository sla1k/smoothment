using Smoothment.Models;

namespace Smoothment.Commands.Convert;

public record ConvertCommandOptions(
    IEnumerable<BankStatementFile> InputFiles,
    string? OutputPath,
    string Format);
