using Smoothment.Converters.Santander;
using Microsoft.Extensions.Logging.Abstractions;

namespace Smoothment.Tests.Converters.Santander;

public class SantanderTransactionsConverterTests
{
    private readonly SantanderTransactionsConverter _converter =
        new(NullLogger<SantanderTransactionsConverter>.Instance);

    [Fact]
    public async Task ConvertAsync_ValidFile_ReturnsTransactions()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/Santander/santander.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert
        Assert.Equal(4, transactions.Count);
        Assert.All(transactions, t => Assert.Equal("santander", t.Bank));
        Assert.All(transactions, t => Assert.Equal("testAccount", t.Account));
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_ParsesDateCorrectly()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/Santander/santander.xlsx", CancellationToken.None);
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
    public async Task ConvertAsync_ValidFile_ExtractsCurrency()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/Santander/santander.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert
        Assert.All(transactions, t => Assert.Equal("EUR", t.Currency));
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_DetectsTransfers()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/Santander/santander.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert - check transfer transactions
        var transfersIn = transactions.Where(t => t.IsTransfer && t.Amount > 0).ToList();
        var transfersOut = transactions.Where(t => t.IsTransfer && t.Amount < 0).ToList();

        Assert.Equal(2, transfersIn.Count); // Two transfers received (100 and 10)
        Assert.Single(transfersOut); // One transfer out (-10)

        Assert.All(transfersIn, t => Assert.Equal("Transfer received", t.Payee));
        Assert.All(transfersOut, t => Assert.Equal("Transfer completed", t.Payee));
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_HandlesBothIncomeAndExpenses()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/Santander/santander.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert
        var hasNegative = transactions.Any(t => t.Amount < 0);
        var hasPositive = transactions.Any(t => t.Amount > 0);

        Assert.True(hasNegative, "Should have negative amounts (expenses)");
        Assert.True(hasPositive, "Should have positive amounts (income)");

        // Verify specific amounts
        Assert.Contains(transactions, t => t.Amount == 100); // Transfer received
        Assert.Contains(transactions, t => t.Amount == 10); // Transfer received
        Assert.Contains(transactions, t => t.Amount == -43.15m); // Card payment
        Assert.Contains(transactions, t => t.Amount == -10); // Transfer out
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_ParsesPayeeFromConcepto()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/Santander/santander.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert - non-transfer transaction should have payee from CONCEPTO
        var cardPayment = transactions.FirstOrDefault(t => !t.IsTransfer);
        Assert.NotNull(cardPayment);
        Assert.Contains("Acme Restaurant", cardPayment.Payee);

        // Check that payees are not empty
        Assert.All(transactions, t => Assert.False(string.IsNullOrWhiteSpace(t.Payee)));
    }

    [Fact]
    public async Task ConvertAsync_ValidFile_StoresConceptoAsDescription()
    {
        // Arrange
        var fileContent = await File.ReadAllBytesAsync("Converters/Santander/santander.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        // Act
        var transactions = await _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        // Assert - all transactions should have description from CONCEPTO
        Assert.All(transactions, t => Assert.False(string.IsNullOrWhiteSpace(t.Description)));

        // Transfer transactions should have original concepto in description
        var transfer = transactions.FirstOrDefault(t => t.IsTransfer);
        Assert.NotNull(transfer);
        Assert.Contains("Transferencia", transfer.Description);
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
    public async Task ConvertAsync_EmptyFile_ThrowsException()
    {
        // Arrange
        var fileStream = new MemoryStream([]);

        // Act & Assert
        await Assert.ThrowsAsync<FileFormatException>(() =>
            _converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None));
    }
}
