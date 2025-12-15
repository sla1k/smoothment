using System.Globalization;
using Smoothment.Converters;
using Smoothment.Exporters;
using CsvHelper;

namespace Smoothment.Tests.Exporters;

public class CsvTransactionExporterTests
{
    [Fact]
    public void Key_ReturnsCorrectValue()
    {
        var exporter = new CsvTransactionExporter();

        Assert.Equal("csv", exporter.Key);
    }

    [Fact]
    public void FileExtension_ReturnsCorrectValue()
    {
        var exporter = new CsvTransactionExporter();

        Assert.Equal(".csv", exporter.FileExtension);
    }

    [Fact]
    public async Task ExportAsync_EmptyTransactions_CreatesEmptyFile()
    {
        var exporter = new CsvTransactionExporter();
        var transactions = new List<Transaction>();
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            Assert.True(File.Exists(tempFile));
            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);
            // CSV should only have headers
            var lines = content.Split('\n', StringSplitOptions.RemoveEmptyEntries);
            Assert.Single(lines); // Only header line
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_SingleTransaction_WritesCorrectly()
    {
        var exporter = new CsvTransactionExporter();
        var transaction = new Transaction
        {
            Bank = "tbank",
            Account = "checking",
            Payee = "Test Payee",
            Amount = -100.50m,
            Category = "Food",
            Description = "Test Description",
            Date = new DateTime(2025, 10, 11, 14, 30, 0),
            Currency = "USD",
            IsTransfer = false
        };
        var transactions = new List<Transaction> { transaction };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            Assert.True(File.Exists(tempFile));

            // Read back and verify
            using var reader = new StreamReader(tempFile);
            using var csv = new CsvReader(reader, CultureInfo.InvariantCulture);
            var records = csv.GetRecords<Transaction>().ToList();

            Assert.Single(records);
            var record = records[0];
            Assert.Equal("tbank", record.Bank);
            Assert.Equal("checking", record.Account);
            Assert.Equal("Test Payee", record.Payee);
            Assert.Equal(-100.50m, record.Amount);
            Assert.Equal("Food", record.Category);
            Assert.Equal("Test Description", record.Description);
            Assert.Equal(new DateTime(2025, 10, 11, 14, 30, 0), record.Date);
            Assert.Equal("USD", record.Currency);
            Assert.False(record.IsTransfer);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_MultipleTransactions_WritesAllRecords()
    {
        var exporter = new CsvTransactionExporter();
        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Payee 1",
                Amount = -50.00m,
                Category = "Food",
                Description = "Desc 1",
                Date = new DateTime(2025, 10, 1),
                Currency = "USD",
                IsTransfer = false
            },
            new()
            {
                Bank = "revolut",
                Account = "main",
                Payee = "Payee 2",
                Amount = 200.00m,
                Category = "Income",
                Description = "Desc 2",
                Date = new DateTime(2025, 10, 2),
                Currency = "EUR",
                IsTransfer = false
            },
            new()
            {
                Bank = "wise",
                Account = "savings",
                Payee = "Payee 3",
                Amount = -30.00m,
                Category = "Transfer",
                Description = null,
                Date = new DateTime(2025, 10, 3),
                Currency = "GBP",
                IsTransfer = true
            }
        };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            // Read back and verify
            using var reader = new StreamReader(tempFile);
            using var csv = new CsvReader(reader, CultureInfo.InvariantCulture);
            var records = csv.GetRecords<Transaction>().ToList();

            Assert.Equal(3, records.Count);
            Assert.Equal("Payee 1", records[0].Payee);
            Assert.Equal("Payee 2", records[1].Payee);
            Assert.Equal("Payee 3", records[2].Payee);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_CancellationRequested_ThrowsException()
    {
        var exporter = new CsvTransactionExporter();
        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Test",
                Amount = -100m,
                Category = "Food",
                Description = "Test",
                Date = DateTime.Now,
                Currency = "USD",
                IsTransfer = false
            }
        };
        var tempFile = Path.GetTempFileName();
        var cts = new CancellationTokenSource();
        cts.Cancel();

        try
        {
            // CsvHelper wraps OperationCanceledException in WriterException
            var exception = await Assert.ThrowsAnyAsync<Exception>(async () =>
                await exporter.ExportAsync(transactions, tempFile, cts.Token)
            );

            // Verify that the cancellation was the root cause
            Assert.True(exception is OperationCanceledException ||
                        exception.InnerException is OperationCanceledException);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_TransactionWithNullFields_HandlesCorrectly()
    {
        var exporter = new CsvTransactionExporter();
        var transaction = new Transaction
        {
            Bank = "tbank",
            Account = "checking",
            Payee = "Test Payee",
            Amount = -100.00m,
            Category = null,
            Description = null,
            Date = new DateTime(2025, 10, 11),
            Currency = "USD",
            IsTransfer = false
        };
        var transactions = new List<Transaction> { transaction };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            // Read back and verify
            using var reader = new StreamReader(tempFile);
            using var csv = new CsvReader(reader, CultureInfo.InvariantCulture);
            var records = csv.GetRecords<Transaction>().ToList();

            Assert.Single(records);
            // CsvHelper deserializes null values as empty strings
            Assert.True(string.IsNullOrEmpty(records[0].Category));
            Assert.True(string.IsNullOrEmpty(records[0].Description));
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }
}
