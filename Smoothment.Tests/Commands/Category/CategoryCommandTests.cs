using System.CommandLine;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Smoothment.Commands.Category;
using Smoothment.Database;

namespace Smoothment.Tests.Commands.Category;

public class CategoryCommandTests : IDisposable
{
    private readonly SmoothmentDbContext _context;
    private readonly IServiceProvider _serviceProvider;

    public CategoryCommandTests()
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
    public async Task Add_CreatesNewCategory()
    {
        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("add Groceries").InvokeAsync();

        Assert.Equal(0, result);
        var category = await _context.Categories.FirstOrDefaultAsync(c => c.Name == "Groceries");
        Assert.NotNull(category);
    }

    [Fact]
    public async Task Add_ExistingCategory_ReturnsError()
    {
        _context.Categories.Add(new Smoothment.Database.Category { Name = "Groceries" });
        await _context.SaveChangesAsync();

        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("add Groceries").InvokeAsync();

        Assert.Equal(1, result);
    }

    [Fact]
    public async Task Remove_DeletesCategory()
    {
        _context.Categories.Add(new Smoothment.Database.Category { Name = "Groceries" });
        await _context.SaveChangesAsync();

        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("remove Groceries").InvokeAsync();

        Assert.Equal(0, result);
        var category = await _context.Categories.FirstOrDefaultAsync(c => c.Name == "Groceries");
        Assert.Null(category);
    }

    [Fact]
    public async Task Remove_NonExistentCategory_ReturnsError()
    {
        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("remove NonExistent").InvokeAsync();

        Assert.Equal(1, result);
    }

    [Fact]
    public async Task Synonym_AddsSynonymToCategory()
    {
        _context.Categories.Add(new Smoothment.Database.Category { Name = "Groceries" });
        await _context.SaveChangesAsync();

        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("synonym Groceries supermarket").InvokeAsync();

        Assert.Equal(0, result);
        var category = await _context.Categories.FirstOrDefaultAsync(c => c.Name == "Groceries");
        Assert.NotNull(category);
        Assert.Contains("supermarket", category.Synonymous);
    }

    [Fact]
    public async Task Synonym_MultipleSynonyms_AllAdded()
    {
        _context.Categories.Add(new Smoothment.Database.Category { Name = "Groceries" });
        await _context.SaveChangesAsync();

        var command = CategoryCommand.Create(_serviceProvider);
        await command.Parse("synonym Groceries supermarket").InvokeAsync();
        await command.Parse("synonym Groceries \"food store\"").InvokeAsync();

        var category = await _context.Categories.FirstOrDefaultAsync(c => c.Name == "Groceries");
        Assert.NotNull(category);
        Assert.Equal(2, category.Synonymous.Length);
        Assert.Contains("supermarket", category.Synonymous);
        Assert.Contains("food store", category.Synonymous);
    }

    [Fact]
    public async Task Synonym_DuplicateSynonym_NotAdded()
    {
        _context.Categories.Add(new Smoothment.Database.Category
        {
            Name = "Groceries",
            Synonymous = ["supermarket"]
        });
        await _context.SaveChangesAsync();

        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("synonym Groceries supermarket").InvokeAsync();

        Assert.Equal(0, result);
        var category = await _context.Categories.FirstOrDefaultAsync(c => c.Name == "Groceries");
        Assert.NotNull(category);
        Assert.Single(category.Synonymous);
    }

    [Fact]
    public async Task Synonym_NonExistentCategory_ReturnsError()
    {
        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("synonym NonExistent synonym").InvokeAsync();

        Assert.Equal(1, result);
    }

    [Fact]
    public async Task List_EmptyDatabase_ReturnsSuccess()
    {
        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("list").InvokeAsync();

        Assert.Equal(0, result);
    }

    [Fact]
    public async Task List_WithCategories_ReturnsSuccess()
    {
        _context.Categories.Add(new Smoothment.Database.Category { Name = "Groceries" });
        _context.Categories.Add(new Smoothment.Database.Category { Name = "Entertainment" });
        await _context.SaveChangesAsync();

        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("list").InvokeAsync();

        Assert.Equal(0, result);
    }

    [Fact]
    public async Task DefaultAction_ListsCategories()
    {
        _context.Categories.Add(new Smoothment.Database.Category { Name = "Groceries" });
        await _context.SaveChangesAsync();

        var command = CategoryCommand.Create(_serviceProvider);
        var result = await command.Parse("").InvokeAsync();

        Assert.Equal(0, result);
    }
}
