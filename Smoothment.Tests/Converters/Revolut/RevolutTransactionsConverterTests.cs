using System.Text;
using Smoothment.Converters.Revolut;
using CsvHelper;

namespace Smoothment.Tests.Converters.Revolut;

public class RevolutTransactionsConverterTests
{
    [Fact]
    public async Task ConvertAsync_ValidFile_ReturnsTransactions()
    {
        var converter = new RevolutTransactionsConverter();
        var fileContent = await File.ReadAllTextAsync("Converters/Revolut/revolut_transactions.csv", Encoding.UTF8,
            CancellationToken.None);
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(fileContent));

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        Assert.Equal(32, transactions.Count);
        Assert.Equal("testAccount", transactions.First().Account);
        Assert.Equal(new DateTime(2025, 02, 25, 01, 00, 00), transactions.First().Date);
        Assert.Equal(-29.90m, transactions.First().Amount);
        Assert.Equal("To Telecom Company", transactions.First().Payee);
    }

    [Fact]
    public async Task ConvertAsync_EmptyFile_ReturnsEmptyCollection()
    {
        var converter = new RevolutTransactionsConverter();
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(""));

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        Assert.Empty(transactions);
    }

    [Fact]
    public async Task ConvertAsync_InvalidFormat_ThrowsException()
    {
        var converter = new RevolutTransactionsConverter();
        const string fileContent = "Invalid,CSV,Content";
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(fileContent));

        await Assert.ThrowsAsync<HeaderValidationException>(() =>
            converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None));
    }

    [Fact]
    public async Task ConvertAsync_TransferType_MarksAsTransfer()
    {
        var converter = new RevolutTransactionsConverter();
        var fileContent = await File.ReadAllTextAsync("Converters/Revolut/revolut_transactions.csv", Encoding.UTF8,
            CancellationToken.None);
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(fileContent));

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Check that TRANSFER type transactions are marked as transfers
        var transferTransactions = transactions.Where(t => t.IsTransfer).ToList();
        Assert.NotEmpty(transferTransactions);

        // Verify first transfer transaction from CSV (line 2 and 3 have TRANSFER type)
        var firstTransfer = transactions.First(t => t.IsTransfer);
        Assert.True(firstTransfer.IsTransfer);
    }
}
