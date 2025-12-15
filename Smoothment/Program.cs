using System.CommandLine;
using System.Diagnostics;
using Smoothment.Commands;
using Smoothment.Commands.Convert;
using Smoothment.Converters;
using Smoothment.Database;
using Smoothment.Exporters;
using Smoothment.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

var host = CreateHost();

using (var scope = host.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();
    db.Database.Migrate();
}

var rootCommand = new RootCommand(
    """
    CLI tool for converting bank transaction exports into unified formats.

    Supported banks: Revolut, Wise, BBVA, Santander and many more.
    Input formats: CSV, Excel (.xlsx), OFX
    Output formats: CSV, OFX

    Features:
      - Batch processing of multiple bank files in single command
      - Transaction enrichment via SQLite database (payees, categories)
      - Automatic encoding detection (UTF-8, Windows-1251)
      - Transfer detection and type classification (Expense/TopUp)
    """);
rootCommand.Subcommands.Add(ConvertCommand.Create(host.Services));

return rootCommand.Parse(args).Invoke();

IHost CreateHost()
{
    var exePath = Path.GetDirectoryName(
        Process.GetCurrentProcess().MainModule?.FileName
    ) ?? AppContext.BaseDirectory;

    var builder = Host.CreateApplicationBuilder();

    var dbPath = Path.Combine(exePath, "smoothment.db");
    builder.Services.AddDbContext<SmoothmentDbContext>(options =>
        options.UseSqlite($"Data Source={dbPath}"));

    // Converters
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

    // Exporters
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

    // Services
    builder.Services.AddScoped<ITransactionEnricher, TransactionEnricher>();
    builder.Services.AddScoped<ITransactionProcessingService, TransactionProcessingService>();

    // Command handlers
    builder.Services.AddScoped<ICommandHandler<ConvertCommandOptions>, ConvertCommandHandler>();

    return builder.Build();
}
