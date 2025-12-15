using System.Text;
using Smoothment.Converters.TBank;

namespace Smoothment.Tests.Converters.TBank;

// ReSharper disable once InconsistentNaming
public class TSmoothmentTests
{
    public TSmoothmentTests()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
    }

    [Fact]
    public async Task ConvertAsync_ValidUtf8File_ReturnsTransactions()
    {
        var converter = new TSmoothment();
        var fileStream = File.OpenRead("Converters/TBank/tbank_transactions.csv");

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        Assert.Equal(23, transactions.Count);
        Assert.Equal(new DateTimeOffset(2025, 04, 02, 15, 28, 24, TimeSpan.FromHours(3)), transactions.First().Date);
        Assert.Equal(-929.00m, transactions.First().Amount);
        Assert.Equal("Фастфуд", transactions.First().Category);
        Assert.Equal("Пиццерия", transactions.First().Payee);
    }

    [Fact]
    public async Task ConvertAsync_ValidWin1251File_ReturnsTransactions()
    {
        var converter = new TSmoothment();
        var fileStream = File.OpenRead("Converters/TBank/tbank_transactions_win1251.csv");

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        Assert.Equal(23, transactions.Count);
        Assert.Equal(new DateTimeOffset(2025, 04, 02, 15, 28, 24, TimeSpan.FromHours(3)), transactions.First().Date);
        Assert.Equal(-929.00m, transactions.First().Amount);
        Assert.Equal("Фастфуд", transactions.First().Category);
        Assert.Equal("Пиццерия", transactions.First().Payee);
    }

    [Fact]
    public async Task ConvertAsync_EmptyFile_ReturnsEmptyCollection()
    {
        var converter = new TSmoothment();
        var fileStream = new MemoryStream([]);

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        Assert.Empty(transactions);
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_MapsDescriptionField()
    {
        var converter = new TSmoothment();
        var fileStream = File.OpenRead("Converters/TBank/tbank_transactions.csv");

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Verify that Description is mapped from "Описание" column
        var transferTransaction = transactions.FirstOrDefault(t =>
            t.Category == "Переводы" && t.Description == "Перевод между счетами");

        Assert.NotNull(transferTransaction);
        Assert.Equal("Перевод между счетами", transferTransaction.Description);
        Assert.Equal("Переводы", transferTransaction.Category);
    }

    [Fact]
    public async Task ConvertAsync_ValidOfxFile_ReturnsTransactions()
    {
        var converter = new TSmoothment();
        var fileStream = File.OpenRead("Converters/TBank/tbank_transaction.ofx");

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // The OFX file contains 21 transactions across 4 accounts
        Assert.Equal(21, transactions.Count);
        Assert.All(transactions, t => Assert.Equal("tbank", t.Bank));
        Assert.All(transactions, t => Assert.Equal("testAccount", t.Account));
    }

    [Fact]
    public async Task ConvertAsync_OfxFile_ParsesTransactionCorrectly()
    {
        var converter = new TSmoothment();
        var fileStream = File.OpenRead("Converters/TBank/tbank_transaction.ofx");

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Find the specific transaction: Yota payment
        var yotaTransaction = transactions.FirstOrDefault(t =>
            t.Payee == "Yota" && t.Amount == -100.00m);

        Assert.NotNull(yotaTransaction);
        Assert.Equal(new DateTimeOffset(2025, 10, 09, 12, 02, 49, TimeSpan.FromHours(3)), yotaTransaction.Date);
        Assert.Equal(-100.00m, yotaTransaction.Amount);
        Assert.Equal("Yota", yotaTransaction.Payee);
        Assert.Equal("Связь", yotaTransaction.Category);
        Assert.Equal("RUB", yotaTransaction.Currency);
        Assert.False(yotaTransaction.IsTransfer);
    }

    [Fact]
    public async Task ConvertAsync_OfxFile_DetectsTransfers()
    {
        var converter = new TSmoothment();
        var fileStream = File.OpenRead("Converters/TBank/tbank_transaction.ofx");

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Find transfer transactions
        var transferTransactions = transactions.Where(t => t.IsTransfer).ToList();

        Assert.Equal(2, transferTransactions.Count);
        Assert.All(transferTransactions, t =>
        {
            Assert.Equal("Переводы", t.Category);
            Assert.Contains("Между своими счетами", t.Payee);
        });
    }

    [Fact]
    public async Task ConvertAsync_OfxFile_ParsesMultipleAccountTypes()
    {
        var converter = new TSmoothment();
        var fileStream = File.OpenRead("Converters/TBank/tbank_transaction.ofx");

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Verify we have transactions from different account types
        // The file contains transactions from CHECKING, SAVINGS, and CREDITLINE accounts
        Assert.True(transactions.Count > 0);

        // Check that we have both income and expense transactions
        var incomeTransactions = transactions.Where(t => t.Amount > 0).ToList();
        var expenseTransactions = transactions.Where(t => t.Amount < 0).ToList();

        Assert.True(incomeTransactions.Count > 0);
        Assert.True(expenseTransactions.Count > 0);
    }
}
