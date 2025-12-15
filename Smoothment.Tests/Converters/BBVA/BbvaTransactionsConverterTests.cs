using Smoothment.Converters.Bbva;
using Microsoft.Extensions.Logging.Abstractions;

namespace Smoothment.Tests.Converters.BBVA;

public class BbvaTransactionsConverterTests
{
    private readonly BbvaTransactionsConverter _converter = new(NullLogger<BbvaTransactionsConverter>.Instance);

    [Fact]
    public async Task ConvertAsync_ValidFile_ReturnsTransactions()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/BBVA/bbva.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert
        Assert.Equal(14, transactions.Count);
        Assert.All(transactions, t => Assert.Equal("bbva", t.Bank));
        Assert.All(transactions, t => Assert.Equal("testAccount", t.Account));
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_ParsesDateCorrectly()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/BBVA/bbva.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert
        var firstTransaction = transactions.First();
        Assert.Equal(new DateTimeOffset(2025, 12, 5, 0, 0, 0, TimeSpan.FromHours(1)), firstTransaction.Date);

        // Verify all dates are valid
        Assert.All(transactions, t =>
        {
            Assert.NotEqual(DateTimeOffset.MinValue, t.Date);
            Assert.InRange(t.Date.Year, 2020, 2030);
        });
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_ExtractsCurrencyFromColumn()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/BBVA/bbva.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert
        Assert.All(transactions, t => Assert.Equal("EUR", t.Currency));
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_ParsesCommentsAsDescription()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/BBVA/bbva.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert - first transaction should have description with card number
        var firstTransaction = transactions.First();
        Assert.NotNull(firstTransaction.Description);
        Assert.Contains("0000000000000000", firstTransaction.Description);
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_DetectsTransfers()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/BBVA/bbva.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert - check specific transfer transactions
        var transferReceived = transactions.FirstOrDefault(t => t.Amount == 200);
        Assert.NotNull(transferReceived);
        Assert.True(transferReceived.IsTransfer);
        Assert.Equal("Transfer received", transferReceived.Payee);

        var transferCompleted = transactions.FirstOrDefault(t => t.Amount == -10);
        Assert.NotNull(transferCompleted);
        Assert.True(transferCompleted.IsTransfer);
        Assert.Equal("Transfer completed", transferCompleted.Payee);
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_HandlesBothIncomeAndExpenses()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/BBVA/bbva.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert
        var hasNegative = transactions.Any(t => t.Amount < 0);
        var hasPositive = transactions.Any(t => t.Amount > 0);

        Assert.True(hasNegative, "Should have negative amounts (expenses)");
        Assert.True(hasPositive, "Should have positive amounts (income)");

        // Verify specific amounts
        Assert.Contains(transactions, t => t.Amount == 200); // Transfer received
        Assert.Contains(transactions, t => t.Amount == 80); // Another income
        Assert.Contains(transactions, t => t.Amount == -95); // Card payment
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_ParsesPayeeFromItemColumn()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/BBVA/bbva.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert - check specific payees from the file
        var firstTransaction = transactions.First();
        Assert.Equal("John Smith store examplecityname es", firstTransaction.Payee);

        // Check that payees are not empty
        Assert.All(transactions, t => Assert.False(string.IsNullOrWhiteSpace(t.Payee)));
    }

    [Fact]
    public async Task ConvertAsync_InvalidFormat_ThrowsException()
    {
        // Arrange
        var fileContent = "Invalid,Excel,Content"u8.ToArray();
        var fileStream = new MemoryStream(fileContent);

        // Act & Assert
        await Assert.ThrowsAsync<FileFormatException>(() =>
            _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None));
    }

    [Fact]
    public async Task ConvertAsync_EmptyFile_ReturnsEmptyCollection()
    {
        // Arrange
        var fileStream = new MemoryStream([]);

        // Act & Assert
        await Assert.ThrowsAsync<FileFormatException>(() =>
            _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None));
    }
}
