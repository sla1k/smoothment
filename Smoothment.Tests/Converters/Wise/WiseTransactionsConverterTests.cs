using System.Text;
using Smoothment.Converters.Wise;
using CsvHelper;
using MissingFieldException = CsvHelper.MissingFieldException;

namespace Smoothment.Tests.Converters.Wise;

public class WiseTransactionsConverterTests
{
    [Fact]
    public async Task ConvertAsync_ValidFile_ReturnsTransactions()
    {
        var converter = new WiseTransactionsConverter();
        var fileContent = await File.ReadAllTextAsync("Converters/Wise/wise_transactions.csv", Encoding.UTF8,
            CancellationToken.None);
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(fileContent));

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        Assert.Equal(8, transactions.Count);
        Assert.Equal(new DateTime(2025, 03, 01, 18, 00, 02, 198), transactions.First().Date);
        Assert.Equal(-61.13m, transactions.First().Amount);
        Assert.Equal("Department", transactions.First().Payee);
    }

    [Fact]
    public async Task ConvertAsync_EmptyFile_ReturnsEmptyCollection()
    {
        var converter = new WiseTransactionsConverter();
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(""));

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        Assert.Empty(transactions);
    }

    [Fact]
    public async Task ConvertAsync_InvalidFormat_ThrowsException()
    {
        var converter = new WiseTransactionsConverter();
        var fileContent = "Invalid,CSV,Content";
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(fileContent));

        await Assert.ThrowsAsync<HeaderValidationException>(() =>
            converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None));
    }

    [Fact]
    public async Task ConvertAsync_MissingFields_ThrowsException()
    {
        var converter = new WiseTransactionsConverter();
        const string fileContent =
            "\"TransferWise ID\",Date,\"Date Time\",Amount,Currency,Description,\"Payment Reference\",\"Running Balance\",\"Exchange From\",\"Exchange To\",\"Exchange Rate\",\"Payer Name\",\"Payee Name\",\"Payee Account Number\",Merchant,\"Card Last Four Digits\",\"Card Holder Full Name\",Attachment,Note,\"Total fees\",\"Exchange To Amount\",\"Transaction Type\",\"Transaction Details Type\"\n\nID,01-03-2025,01-03-2025 18:00:02.198,-61.13,";
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(fileContent));

        await Assert.ThrowsAsync<MissingFieldException>(() =>
            converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None));
    }

    [Fact]
    public async Task ConvertAsync_TransferWiseId_MarksAsTransfer()
    {
        var converter = new WiseTransactionsConverter();
        var fileContent = await File.ReadAllTextAsync("Converters/Wise/wise_transactions.csv", Encoding.UTF8,
            CancellationToken.None);
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(fileContent));

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Check that transactions with TransferWise ID starting with "TRANSFER-" are marked as transfers
        var transferTransactions = transactions.Where(t => t.IsTransfer).ToList();
        Assert.NotEmpty(transferTransactions);

        // Verify the transfer transaction
        var transferTransaction = transferTransactions.First();
        Assert.True(transferTransaction.IsTransfer);
        Assert.Equal(-1900.00m, transferTransaction.Amount);
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_MapsCurrencyField()
    {
        var converter = new WiseTransactionsConverter();
        var fileContent = await File.ReadAllTextAsync("Converters/Wise/wise_transactions.csv", Encoding.UTF8,
            CancellationToken.None);
        var fileStream = new MemoryStream(Encoding.UTF8.GetBytes(fileContent));

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Verify that Currency is mapped from the Currency column
        Assert.All(transactions, t => Assert.Equal("EUR", t.Currency));
    }
}
