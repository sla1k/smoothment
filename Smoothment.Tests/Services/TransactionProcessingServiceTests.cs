using Smoothment.Converters;
using Smoothment.Models;
using Smoothment.Services;
using Moq;

namespace Smoothment.Tests.Services;

public class TransactionProcessingServiceTests : IDisposable
{
    private readonly Mock<ITransactionsConverter> _mockConverter;
    private readonly Mock<ITransactionEnricher> _mockEnricher;
    private readonly TransactionProcessingService _service;
    private readonly string _testFilePath;

    public TransactionProcessingServiceTests()
    {
        _testFilePath = Path.Combine(Path.GetTempPath(), $"test_{Guid.NewGuid()}.csv");
        File.WriteAllText(_testFilePath, "test data");

        _mockConverter = new Mock<ITransactionsConverter>();
        _mockEnricher = new Mock<ITransactionEnricher>();

        Func<string, ITransactionsConverter> converterFactory = _ => _mockConverter.Object;
        _service = new TransactionProcessingService(converterFactory, _mockEnricher.Object);
    }

    public void Dispose()
    {
        if (File.Exists(_testFilePath)) File.Delete(_testFilePath);
    }

    [Fact]
    public async Task ProcessFilesAsync_CallsConverterForEachFile()
    {
        var files = new[]
        {
            new BankStatementFile(_testFilePath, "testbank", "checking")
        };

        var convertedTransactions = new List<Transaction>
        {
            CreateTestTransaction("Merchant1", -10m)
        };

        _mockConverter
            .Setup(c => c.ConvertAsync(It.IsAny<Stream>(), "checking", It.IsAny<CancellationToken>()))
            .ReturnsAsync(convertedTransactions);

        _mockEnricher
            .Setup(e => e.EnrichAsync(It.IsAny<IReadOnlyCollection<Transaction>>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((IReadOnlyCollection<Transaction> t, CancellationToken _) => t.ToList());

        await _service.ProcessFilesAsync(files, CancellationToken.None);

        _mockConverter.Verify(
            c => c.ConvertAsync(It.IsAny<Stream>(), "checking", It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task ProcessFilesAsync_CallsEnricherWithAllTransactions()
    {
        var files = new[]
        {
            new BankStatementFile(_testFilePath, "testbank", "checking")
        };

        var convertedTransactions = new List<Transaction>
        {
            CreateTestTransaction("Merchant1", -10m),
            CreateTestTransaction("Merchant2", -20m)
        };

        _mockConverter
            .Setup(c => c.ConvertAsync(It.IsAny<Stream>(), "checking", It.IsAny<CancellationToken>()))
            .ReturnsAsync(convertedTransactions);

        _mockEnricher
            .Setup(e => e.EnrichAsync(It.IsAny<IReadOnlyCollection<Transaction>>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((IReadOnlyCollection<Transaction> t, CancellationToken _) => t.ToList());

        await _service.ProcessFilesAsync(files, CancellationToken.None);

        _mockEnricher.Verify(
            e => e.EnrichAsync(
                It.Is<IReadOnlyCollection<Transaction>>(t => t.Count == 2),
                It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task ProcessFilesAsync_ReturnsEnrichedTransactions()
    {
        var files = new[]
        {
            new BankStatementFile(_testFilePath, "testbank", "checking")
        };

        var convertedTransactions = new List<Transaction>
        {
            CreateTestTransaction("Merchant1", -10m)
        };

        var enrichedTransactions = new List<Transaction>
        {
            CreateTestTransaction("Enriched Merchant", -10m, "Shopping")
        };

        _mockConverter
            .Setup(c => c.ConvertAsync(It.IsAny<Stream>(), "checking", It.IsAny<CancellationToken>()))
            .ReturnsAsync(convertedTransactions);

        _mockEnricher
            .Setup(e => e.EnrichAsync(It.IsAny<IReadOnlyCollection<Transaction>>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(enrichedTransactions);

        var result = await _service.ProcessFilesAsync(files, CancellationToken.None);

        Assert.Single(result);
        Assert.Equal("Enriched Merchant", result.First().Payee);
        Assert.Equal("Shopping", result.First().Category);
    }

    [Fact]
    public async Task ProcessFilesAsync_AggregatesTransactionsFromMultipleFiles()
    {
        var testFilePath2 = Path.Combine(Path.GetTempPath(), $"test2_{Guid.NewGuid()}.csv");
        File.WriteAllText(testFilePath2, "test data 2");

        try
        {
            var files = new[]
            {
                new BankStatementFile(_testFilePath, "bank1", "account1"),
                new BankStatementFile(testFilePath2, "bank2", "account2")
            };

            var transactions1 = new List<Transaction> { CreateTestTransaction("Merchant1", -10m) };
            var transactions2 = new List<Transaction> { CreateTestTransaction("Merchant2", -20m) };

            _mockConverter
                .Setup(c => c.ConvertAsync(It.IsAny<Stream>(), "account1", It.IsAny<CancellationToken>()))
                .ReturnsAsync(transactions1);

            _mockConverter
                .Setup(c => c.ConvertAsync(It.IsAny<Stream>(), "account2", It.IsAny<CancellationToken>()))
                .ReturnsAsync(transactions2);

            _mockEnricher
                .Setup(e => e.EnrichAsync(It.IsAny<IReadOnlyCollection<Transaction>>(), It.IsAny<CancellationToken>()))
                .ReturnsAsync((IReadOnlyCollection<Transaction> t, CancellationToken _) => t.ToList());

            await _service.ProcessFilesAsync(files, CancellationToken.None);

            _mockEnricher.Verify(
                e => e.EnrichAsync(
                    It.Is<IReadOnlyCollection<Transaction>>(t => t.Count == 2),
                    It.IsAny<CancellationToken>()),
                Times.Once);
        }
        finally
        {
            if (File.Exists(testFilePath2)) File.Delete(testFilePath2);
        }
    }

    private static Transaction CreateTestTransaction(string payee, decimal amount, string? category = null)
    {
        return new Transaction
        {
            Bank = "testbank",
            Account = "checking",
            Payee = payee,
            Amount = amount,
            Category = category,
            Description = null,
            Date = DateTimeOffset.Now,
            Currency = "USD"
        };
    }
}
