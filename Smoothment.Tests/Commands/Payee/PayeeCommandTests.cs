using System.CommandLine;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Smoothment.Commands.Payee;
using Smoothment.Database;

namespace Smoothment.Tests.Commands.Payee;

public class PayeeCommandTests : IDisposable
{
    private readonly SmoothmentDbContext _context;
    private readonly IServiceProvider _serviceProvider;

    public PayeeCommandTests()
    {
        var options = new DbContextOptionsBuilder<SmoothmentDbContext>()
            .UseSqlite("DataSource=:memory:")
            .Options;

        _context = new SmoothmentDbContext(options);
        _context.Database.OpenConnection();
        _context.Database.EnsureCreated();

        var services = new ServiceCollection();
        services.AddSingleton(_context);
        services.AddScoped<SmoothmentDbContext>(_ => _context);
        _serviceProvider = services.BuildServiceProvider();
    }

    public void Dispose()
    {
        _context.Database.CloseConnection();
        _context.Dispose();
    }

    [Fact]
    public async Task Add_CreatesNewPayee()
    {
        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("add Starbucks").InvokeAsync();

        Assert.Equal(0, result);
        var payee = await _context.Payees.FirstOrDefaultAsync(p => p.Name == "Starbucks");
        Assert.NotNull(payee);
    }

    [Fact]
    public async Task Add_WithExpenseMetadata_SetsFields()
    {
        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse(
            "add Starbucks --expense-category=Coffee --expense-description=\"Coffee shop\""
        ).InvokeAsync();

        Assert.Equal(0, result);
        var payee = await _context.Payees.FirstOrDefaultAsync(p => p.Name == "Starbucks");
        Assert.NotNull(payee);
        Assert.Equal("Coffee", payee.ExpenseCategory);
        Assert.Equal("Coffee shop", payee.ExpenseDescription);
    }

    [Fact]
    public async Task Add_WithTopUpMetadata_SetsFields()
    {
        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse(
            "add Employer --topup-category=Salary --topup-description=\"Monthly salary\""
        ).InvokeAsync();

        Assert.Equal(0, result);
        var payee = await _context.Payees.FirstOrDefaultAsync(p => p.Name == "Employer");
        Assert.NotNull(payee);
        Assert.Equal("Salary", payee.TopUpCategory);
        Assert.Equal("Monthly salary", payee.TopUpDescription);
    }

    [Fact]
    public async Task Add_ExistingPayee_ReturnsError()
    {
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Starbucks",
            Synonymous = []
        });
        await _context.SaveChangesAsync();

        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("add Starbucks").InvokeAsync();

        Assert.Equal(1, result);
    }

    [Fact]
    public async Task Remove_DeletesPayee()
    {
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Starbucks",
            Synonymous = []
        });
        await _context.SaveChangesAsync();

        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("remove Starbucks").InvokeAsync();

        Assert.Equal(0, result);
        var payee = await _context.Payees.FirstOrDefaultAsync(p => p.Name == "Starbucks");
        Assert.Null(payee);
    }

    [Fact]
    public async Task Remove_NonExistentPayee_ReturnsError()
    {
        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("remove NonExistent").InvokeAsync();

        Assert.Equal(1, result);
    }

    [Fact]
    public async Task Synonym_AddsSynonymToPayee()
    {
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Starbucks",
            Synonymous = []
        });
        await _context.SaveChangesAsync();

        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("synonym Starbucks \"STARBUCKS CORP\"").InvokeAsync();

        Assert.Equal(0, result);
        var payee = await _context.Payees.FirstOrDefaultAsync(p => p.Name == "Starbucks");
        Assert.NotNull(payee);
        Assert.Contains("STARBUCKS CORP", payee.Synonymous);
    }

    [Fact]
    public async Task Synonym_MultipleSynonyms_AllAdded()
    {
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Starbucks",
            Synonymous = []
        });
        await _context.SaveChangesAsync();

        var command = PayeeCommand.Create(_serviceProvider);
        await command.Parse("synonym Starbucks \"STARBUCKS CORP\"").InvokeAsync();
        await command.Parse("synonym Starbucks \"Starbucks Coffee\"").InvokeAsync();

        var payee = await _context.Payees.FirstOrDefaultAsync(p => p.Name == "Starbucks");
        Assert.NotNull(payee);
        Assert.Equal(2, payee.Synonymous.Length);
        Assert.Contains("STARBUCKS CORP", payee.Synonymous);
        Assert.Contains("Starbucks Coffee", payee.Synonymous);
    }

    [Fact]
    public async Task Synonym_PreservesExistingMetadata()
    {
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Starbucks",
            ExpenseCategory = "Coffee",
            ExpenseDescription = "Coffee shop",
            TopUpCategory = "Refund",
            TopUpDescription = "Refund from coffee",
            Synonymous = []
        });
        await _context.SaveChangesAsync();

        var command = PayeeCommand.Create(_serviceProvider);
        await command.Parse("synonym Starbucks \"STARBUCKS CORP\"").InvokeAsync();

        var payee = await _context.Payees.FirstOrDefaultAsync(p => p.Name == "Starbucks");
        Assert.NotNull(payee);
        Assert.Equal("Coffee", payee.ExpenseCategory);
        Assert.Equal("Coffee shop", payee.ExpenseDescription);
        Assert.Equal("Refund", payee.TopUpCategory);
        Assert.Equal("Refund from coffee", payee.TopUpDescription);
    }

    [Fact]
    public async Task Synonym_DuplicateSynonym_NotAdded()
    {
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Starbucks",
            Synonymous = ["STARBUCKS CORP"]
        });
        await _context.SaveChangesAsync();

        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("synonym Starbucks \"STARBUCKS CORP\"").InvokeAsync();

        Assert.Equal(0, result);
        var payee = await _context.Payees.FirstOrDefaultAsync(p => p.Name == "Starbucks");
        Assert.NotNull(payee);
        Assert.Single(payee.Synonymous);
    }

    [Fact]
    public async Task Synonym_CaseInsensitiveDuplicateCheck()
    {
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Starbucks",
            Synonymous = ["STARBUCKS CORP"]
        });
        await _context.SaveChangesAsync();

        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("synonym Starbucks \"starbucks corp\"").InvokeAsync();

        Assert.Equal(0, result);
        var payee = await _context.Payees.FirstOrDefaultAsync(p => p.Name == "Starbucks");
        Assert.NotNull(payee);
        Assert.Single(payee.Synonymous);
    }

    [Fact]
    public async Task Synonym_NonExistentPayee_ReturnsError()
    {
        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("synonym NonExistent synonym").InvokeAsync();

        Assert.Equal(1, result);
    }

    [Fact]
    public async Task List_EmptyDatabase_ReturnsSuccess()
    {
        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("list").InvokeAsync();

        Assert.Equal(0, result);
    }

    [Fact]
    public async Task List_WithPayees_ReturnsSuccess()
    {
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Starbucks",
            Synonymous = []
        });
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Amazon",
            Synonymous = []
        });
        await _context.SaveChangesAsync();

        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("list").InvokeAsync();

        Assert.Equal(0, result);
    }

    [Fact]
    public async Task DefaultAction_ListsPayees()
    {
        _context.Payees.Add(new Smoothment.Database.Payee
        {
            Name = "Starbucks",
            Synonymous = []
        });
        await _context.SaveChangesAsync();

        var command = PayeeCommand.Create(_serviceProvider);
        var result = await command.Parse("").InvokeAsync();

        Assert.Equal(0, result);
    }
}
