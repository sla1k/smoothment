using Smoothment.Converters;
using Smoothment.Database;
using Smoothment.Services;
using Microsoft.EntityFrameworkCore;

namespace Smoothment.Tests.Services;

public class TransactionEnricherTests : IDisposable
{
    private readonly SmoothmentDbContext _context;
    private readonly TransactionEnricher _enricher;

    public TransactionEnricherTests()
    {
        var options = new DbContextOptionsBuilder<SmoothmentDbContext>()
            .UseSqlite("DataSource=:memory:")
            .Options;

        _context = new SmoothmentDbContext(options);
        _context.Database.OpenConnection();
        _context.Database.EnsureCreated();

        _enricher = new TransactionEnricher(_context);
    }

    public void Dispose()
    {
        _context.Database.CloseConnection();
        _context.Dispose();
    }

    [Fact]
    public async Task EnrichAsync_WithMatchingPayee_SetsCanonicalNameAndCategory()
    {
        _context.Payees.Add(new Payee
        {
            Name = "Starbucks",
            ExpenseCategory = "Coffee",
            ExpenseDescription = "Coffee shop",
            TopUpCategory = "Refund",
            TopUpDescription = "Refund from coffee shop",
            Synonymous = ["STARBUCKS CORP", "Starbucks Coffee"]
        });
        await _context.SaveChangesAsync(CancellationToken.None);

        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "test",
                Account = "checking",
                Payee = "STARBUCKS CORP",
                Amount = -5.00m,
                Category = null,
                Description = null,
                Date = DateTimeOffset.Now,
                Currency = "USD"
            }
        };

        var result = await _enricher.EnrichAsync(transactions, CancellationToken.None);

        var enriched = result.Single();
        Assert.Equal("Starbucks", enriched.Payee);
        Assert.Equal("Coffee", enriched.Category);
        Assert.Equal("Coffee shop", enriched.Description);
    }

    [Fact]
    public async Task EnrichAsync_TopUpTransaction_UsesTopUpCategoryAndDescription()
    {
        _context.Payees.Add(new Payee
        {
            Name = "Employer Inc",
            ExpenseCategory = "Business",
            ExpenseDescription = "Business expense",
            TopUpCategory = "Salary",
            TopUpDescription = "Monthly salary",
            Synonymous = []
        });
        await _context.SaveChangesAsync(CancellationToken.None);

        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "test",
                Account = "checking",
                Payee = "Employer Inc",
                Amount = 5000.00m,
                Category = null,
                Description = null,
                Date = DateTimeOffset.Now,
                Currency = "USD"
            }
        };

        var result = await _enricher.EnrichAsync(transactions, CancellationToken.None);

        var enriched = result.Single();
        Assert.Equal("Salary", enriched.Category);
        Assert.Equal("Monthly salary", enriched.Description);
    }

    [Fact]
    public async Task EnrichAsync_WithNoPayeeMatch_NormalizesCategory()
    {
        _context.Categories.Add(new Category
        {
            Name = "Groceries",
            Synonymous = ["grocery", "supermarket", "food store"]
        });
        await _context.SaveChangesAsync(CancellationToken.None);

        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "test",
                Account = "checking",
                Payee = "Unknown Store",
                Amount = -50.00m,
                Category = "supermarket",
                Description = null,
                Date = DateTimeOffset.Now,
                Currency = "USD"
            }
        };

        var result = await _enricher.EnrichAsync(transactions, CancellationToken.None);

        var enriched = result.Single();
        Assert.Equal("Unknown Store", enriched.Payee);
        Assert.Equal("Groceries", enriched.Category);
    }

    [Fact]
    public async Task EnrichAsync_WithNoMatch_LeavesTransactionUnchanged()
    {
        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "test",
                Account = "checking",
                Payee = "Random Merchant",
                Amount = -25.00m,
                Category = "Unknown Category",
                Description = "Original description",
                Date = DateTimeOffset.Now,
                Currency = "USD"
            }
        };

        var result = await _enricher.EnrichAsync(transactions, CancellationToken.None);

        var enriched = result.Single();
        Assert.Equal("Random Merchant", enriched.Payee);
        Assert.Equal("Unknown Category", enriched.Category);
        Assert.Equal("Original description", enriched.Description);
    }

    [Fact]
    public async Task EnrichAsync_PayeeMatchTakesPrecedenceOverCategory()
    {
        _context.Payees.Add(new Payee
        {
            Name = "Amazon",
            ExpenseCategory = "Shopping",
            ExpenseDescription = "Online shopping",
            Synonymous = []
        });
        _context.Categories.Add(new Category
        {
            Name = "Electronics",
            Synonymous = []
        });
        await _context.SaveChangesAsync(CancellationToken.None);

        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "test",
                Account = "checking",
                Payee = "Amazon",
                Amount = -100.00m,
                Category = "Electronics",
                Description = null,
                Date = DateTimeOffset.Now,
                Currency = "USD"
            }
        };

        var result = await _enricher.EnrichAsync(transactions, CancellationToken.None);

        var enriched = result.Single();
        Assert.Equal("Amazon", enriched.Payee);
        Assert.Equal("Shopping", enriched.Category);
        Assert.Equal("Online shopping", enriched.Description);
    }

    [Fact]
    public async Task EnrichAsync_CaseInsensitivePayeeMatching()
    {
        _context.Payees.Add(new Payee
        {
            Name = "Netflix",
            ExpenseCategory = "Entertainment",
            ExpenseDescription = "Streaming service",
            Synonymous = []
        });
        await _context.SaveChangesAsync(CancellationToken.None);

        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "test",
                Account = "checking",
                Payee = "NETFLIX",
                Amount = -15.99m,
                Category = null,
                Description = null,
                Date = DateTimeOffset.Now,
                Currency = "USD"
            }
        };

        var result = await _enricher.EnrichAsync(transactions, CancellationToken.None);

        var enriched = result.Single();
        Assert.Equal("Netflix", enriched.Payee);
        Assert.Equal("Entertainment", enriched.Category);
    }
}
