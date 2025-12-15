using Smoothment.Converters.IdBank;
using Microsoft.Extensions.Logging.Abstractions;

namespace Smoothment.Tests.Converters.IdBank;

public class IdSmoothmentTests
{
    [Fact]
    public async Task ConvertAsync_ValidFile_ReturnsTransactions()
    {
        var converter = new IdSmoothment(NullLogger<IdSmoothment>.Instance);
        var fileContent =
            await File.ReadAllBytesAsync("Converters/IdBank/idbank_transactions.xlsx", CancellationToken.None);
        var fileStream = new MemoryStream(fileContent);

        var transactions = await converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None);

        Assert.Equal(7, transactions.Count);
        Assert.Equal(new DateTimeOffset(2025, 02, 22, 17, 58, 57, TimeSpan.FromHours(4)), transactions.First().Date);
        Assert.Equal(-359.99m, transactions.First().Amount);
        Assert.Equal("Name 1", transactions.First().Payee);
    }

    [Fact]
    public async Task ConvertAsync_InvalidFormat_ThrowsException()
    {
        var converter = new IdSmoothment(NullLogger<IdSmoothment>.Instance);
        var fileContent = "Invalid,Excel,Content"u8.ToArray();
        var fileStream = new MemoryStream(fileContent);

        await Assert.ThrowsAsync<FileFormatException>(() =>
            converter.ConvertAsync(fileStream, "testAccount", CancellationToken.None));
    }
}
