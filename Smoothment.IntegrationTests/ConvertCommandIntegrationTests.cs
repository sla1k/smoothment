using System.CommandLine;
using Smoothment.Commands;
using Smoothment.Commands.Convert;
using Smoothment.Converters;
using Smoothment.Database;
using Smoothment.Exporters;
using Smoothment.Services;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

namespace Smoothment.IntegrationTests;

public class ConvertCommandIntegrationTests : IAsyncDisposable
{
    private readonly IHost _host;
    private readonly SqliteConnection _connection;
    private readonly string _testDataDirectory;

    public ConvertCommandIntegrationTests()
    {
        _connection = new SqliteConnection("DataSource=:memory:");
        _connection.Open();

        _host = CreateTestHost(_connection);
        _testDataDirectory = Path.Combine(Directory.GetCurrentDirectory(), "Converters");

        using var scope = _host.Services.CreateScope();
        var dbContext = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();
        dbContext.Database.EnsureCreated();
    }

    public async ValueTask DisposeAsync()
    {
        await _host.StopAsync();
        _host.Dispose();
        await _connection.DisposeAsync();
    }

    [Fact]
    public async Task ConvertCommand_ValidSingleFile_CreatesOutputFile()
    {
        var inputFile = Path.Combine(_testDataDirectory, "TBank", "tbank_transactions.csv");
        var outputFile = Path.Combine(Path.GetTempPath(), $"output_{Guid.NewGuid()}.csv");

        try
        {
            var exitCode = await InvokeCommandAsync(
                "convert",
                $"--file={inputFile}:tbank:checking",
                $"--output={outputFile}");

            Assert.Equal(0, exitCode);
            Assert.True(File.Exists(outputFile));

            var content = await File.ReadAllTextAsync(outputFile, TestContext.Current.CancellationToken);
            Assert.NotEmpty(content);
            Assert.Contains("tbank", content.ToLowerInvariant());
        }
        finally
        {
            if (File.Exists(outputFile)) File.Delete(outputFile);
        }
    }

    [Fact]
    public async Task ConvertCommand_MultipleFiles_CombinesTransactions()
    {
        var inputFile1 = Path.Combine(_testDataDirectory, "TBank", "tbank_transactions.csv");
        var inputFile2 = Path.Combine(_testDataDirectory, "Revolut", "revolut_transactions.csv");
        var outputFile = Path.Combine(Path.GetTempPath(), $"output_{Guid.NewGuid()}.csv");

        try
        {
            var exitCode = await InvokeCommandAsync(
                "convert",
                $"--file={inputFile1}:tbank:account1",
                $"--file={inputFile2}:revolut:account2",
                $"--output={outputFile}");

            Assert.Equal(0, exitCode);
            Assert.True(File.Exists(outputFile));

            var content = await File.ReadAllTextAsync(outputFile, TestContext.Current.CancellationToken);
            Assert.Contains("tbank", content.ToLowerInvariant());
            Assert.Contains("revolut", content.ToLowerInvariant());
        }
        finally
        {
            if (File.Exists(outputFile)) File.Delete(outputFile);
        }
    }

    [Fact]
    public async Task ConvertCommand_OfxFormat_CreatesOfxFile()
    {
        var inputFile = Path.Combine(_testDataDirectory, "TBank", "tbank_transactions.csv");
        var outputFile = Path.Combine(Path.GetTempPath(), $"output_{Guid.NewGuid()}.ofx");

        try
        {
            var exitCode = await InvokeCommandAsync(
                "convert",
                $"--file={inputFile}:tbank:checking",
                $"--output={outputFile}",
                "--format=ofx");

            Assert.Equal(0, exitCode);
            Assert.True(File.Exists(outputFile));

            var content = await File.ReadAllTextAsync(outputFile, TestContext.Current.CancellationToken);
            Assert.Contains("OFXHEADER:100", content);
            Assert.Contains("<OFX>", content);
            Assert.Contains("</OFX>", content);
        }
        finally
        {
            if (File.Exists(outputFile)) File.Delete(outputFile);
        }
    }

    [Fact]
    public async Task ConvertCommand_DefaultFormat_UsesCsv()
    {
        var inputFile = Path.Combine(_testDataDirectory, "TBank", "tbank_transactions.csv");
        var outputFile = Path.Combine(Path.GetTempPath(), $"output_{Guid.NewGuid()}.csv");

        try
        {
            var exitCode = await InvokeCommandAsync(
                "convert",
                $"--file={inputFile}:tbank:checking",
                $"--output={outputFile}");

            Assert.Equal(0, exitCode);

            var content = await File.ReadAllTextAsync(outputFile, TestContext.Current.CancellationToken);
            Assert.Contains("Bank,Account,Payee", content);
        }
        finally
        {
            if (File.Exists(outputFile)) File.Delete(outputFile);
        }
    }

    [Fact]
    public async Task ConvertCommand_DefaultOutput_CreatesFileInCurrentDirectory()
    {
        var inputFile = Path.Combine(_testDataDirectory, "TBank", "tbank_transactions.csv");
        var expectedOutput = "./converted_transactions.csv";

        try
        {
            var exitCode = await InvokeCommandAsync(
                "convert",
                $"--file={inputFile}:tbank:checking");

            Assert.Equal(0, exitCode);
            Assert.True(File.Exists(expectedOutput));
        }
        finally
        {
            if (File.Exists(expectedOutput)) File.Delete(expectedOutput);
        }
    }

    [Fact]
    public async Task ConvertCommand_InvalidFileFormat_ReturnsNonZeroExitCode()
    {
        var exitCode = await InvokeCommandAsync(
            "convert",
            "--file=path_without_bank_and_account");

        Assert.NotEqual(0, exitCode);
    }

    [Fact]
    public async Task ConvertCommand_PathTraversal_ReturnsNonZeroExitCode()
    {
        var exitCode = await InvokeCommandAsync(
            "convert",
            "--file=../../../etc/passwd:tbank:checking");

        Assert.NotEqual(0, exitCode);
    }

    [Fact]
    public async Task ConvertCommand_MissingFileOption_ReturnsNonZeroExitCode()
    {
        var exitCode = await InvokeCommandAsync("convert");

        Assert.NotEqual(0, exitCode);
    }

    [Fact]
    public async Task ConvertCommand_InvalidFormat_ReturnsNonZeroExitCode()
    {
        var inputFile = Path.Combine(_testDataDirectory, "TBank", "tbank_transactions.csv");

        var exitCode = await InvokeCommandAsync(
            "convert",
            $"--file={inputFile}:tbank:checking",
            "--format=xml");

        Assert.NotEqual(0, exitCode);
    }

    [Fact]
    public async Task ConvertCommand_DifferentBanks_ProcessesCorrectly()
    {
        var outputFile = Path.Combine(Path.GetTempPath(), $"output_{Guid.NewGuid()}.csv");

        var bankFiles = new[]
        {
            (Path.Combine(_testDataDirectory, "TBank", "tbank_transactions.csv"), "tbank"),
            (Path.Combine(_testDataDirectory, "Revolut", "revolut_transactions.csv"), "revolut"),
            (Path.Combine(_testDataDirectory, "Wise", "wise_transactions.csv"), "wise")
        };

        try
        {
            foreach (var (filePath, bank) in bankFiles)
            {
                var exitCode = await InvokeCommandAsync(
                    "convert",
                    $"--file={filePath}:{bank}:testaccount",
                    $"--output={outputFile}");

                Assert.Equal(0, exitCode);
                Assert.True(File.Exists(outputFile));

                var content = await File.ReadAllTextAsync(outputFile, TestContext.Current.CancellationToken);
                Assert.Contains(bank, content.ToLowerInvariant());

                File.Delete(outputFile);
            }
        }
        finally
        {
            if (File.Exists(outputFile)) File.Delete(outputFile);
        }
    }

    [Fact]
    public async Task ConvertCommand_FormatUpperCase_ReturnsNonZeroExitCode()
    {
        var inputFile = Path.Combine(_testDataDirectory, "TBank", "tbank_transactions.csv");
        var outputFile = Path.Combine(Path.GetTempPath(), $"output_{Guid.NewGuid()}.ofx");

        try
        {
            var exitCode = await InvokeCommandAsync(
                "convert",
                $"--file={inputFile}:tbank:checking",
                $"--output={outputFile}",
                "--format=OFX");

            Assert.NotEqual(0, exitCode);
        }
        finally
        {
            if (File.Exists(outputFile)) File.Delete(outputFile);
        }
    }

    private Task<int> InvokeCommandAsync(params string[] args)
    {
        var rootCommand = new RootCommand("Bank transactions converter");
        rootCommand.Subcommands.Add(ConvertCommand.Create(_host.Services));

        try
        {
            return Task.FromResult(rootCommand.Parse(args).Invoke());
        }
        catch
        {
            return Task.FromResult(1);
        }
    }

    private static IHost CreateTestHost(SqliteConnection connection)
    {
        var builder = Host.CreateApplicationBuilder();

        builder.Services.AddDbContext<SmoothmentDbContext>(options =>
            options.UseSqlite(connection));

        builder.Services.Scan(scan => scan
            .FromAssemblyOf<ITransactionsConverter>()
            .AddClasses(classes => classes.AssignableTo<ITransactionsConverter>())
            .AsImplementedInterfaces()
            .WithTransientLifetime());

        builder.Services.AddTransient<Func<string, ITransactionsConverter>>(sp => key =>
        {
            ArgumentException.ThrowIfNullOrEmpty(key);
            var normalizedKey = key.ToLowerInvariant();
            var converters = sp.GetServices<ITransactionsConverter>();
            return converters.FirstOrDefault(c =>
                       string.Equals(c.Key, normalizedKey, StringComparison.OrdinalIgnoreCase))
                   ?? throw new KeyNotFoundException($"Converter with key '{key}' not found");
        });

        builder.Services.Scan(scan => scan
            .FromAssemblyOf<ITransactionExporter>()
            .AddClasses(classes => classes.AssignableTo<ITransactionExporter>())
            .AsImplementedInterfaces()
            .WithTransientLifetime());

        builder.Services.AddTransient<Func<string, ITransactionExporter>>(sp => key =>
        {
            ArgumentException.ThrowIfNullOrEmpty(key);
            var normalizedKey = key.ToLowerInvariant();
            var exporters = sp.GetServices<ITransactionExporter>();
            return exporters.FirstOrDefault(e =>
                       string.Equals(e.Key, normalizedKey, StringComparison.OrdinalIgnoreCase))
                   ?? throw new KeyNotFoundException($"Exporter with key '{key}' not found");
        });

        builder.Services.AddScoped<ITransactionEnricher, TransactionEnricher>();
        builder.Services.AddScoped<ITransactionProcessingService, TransactionProcessingService>();
        builder.Services.AddScoped<ICommandHandler<ConvertCommandOptions>, ConvertCommandHandler>();

        return builder.Build();
    }
}
