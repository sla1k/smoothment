using Microsoft.EntityFrameworkCore;
using Smoothment.Database;

namespace Smoothment.Commands.Synonym;

public class SynonymCommandHandler(SmoothmentDbContext dbContext)
    : ICommandHandler<SynonymCommandOptions>
{
    public async Task<int> ExecuteAsync(SynonymCommandOptions options, CancellationToken cancellationToken)
    {
        return options.TargetType switch
        {
            "category" => await AddCategorySynonymAsync(options.Name, options.SynonymToAdd, cancellationToken),
            "payee" => await AddPayeeSynonymAsync(options.Name, options.SynonymToAdd, cancellationToken),
            _ => throw new ArgumentException($"Unknown target type: {options.TargetType}")
        };
    }

    private async Task<int> AddCategorySynonymAsync(string name, string synonym, CancellationToken cancellationToken)
    {
        var category = await dbContext.Categories
            .FirstOrDefaultAsync(c => c.Name == name, cancellationToken);

        if (category is null)
        {
            Console.WriteLine($"Category '{name}' not found.");
            return 1;
        }

        if (category.Synonymous.Contains(synonym, StringComparer.OrdinalIgnoreCase))
        {
            Console.WriteLine($"Synonym '{synonym}' already exists for category '{name}'.");
            return 0;
        }

        category.Synonymous = [..category.Synonymous, synonym];

        await dbContext.SaveChangesAsync(cancellationToken);
        Console.WriteLine($"Added synonym '{synonym}' to category '{name}'.");
        return 0;
    }

    private async Task<int> AddPayeeSynonymAsync(string name, string synonym, CancellationToken cancellationToken)
    {
        var payee = await dbContext.Payees
            .FirstOrDefaultAsync(p => p.Name == name, cancellationToken);

        if (payee is null)
        {
            Console.WriteLine($"Payee '{name}' not found.");
            return 1;
        }

        if (payee.Synonymous.Contains(synonym, StringComparer.OrdinalIgnoreCase))
        {
            Console.WriteLine($"Synonym '{synonym}' already exists for payee '{name}'.");
            return 0;
        }

        // Payee.Synonymous has init accessor, so we need to create a new entity
        var updatedPayee = new Payee
        {
            Name = payee.Name,
            ExpenseDescription = payee.ExpenseDescription,
            ExpenseCategory = payee.ExpenseCategory,
            TopUpDescription = payee.TopUpDescription,
            TopUpCategory = payee.TopUpCategory,
            Synonymous = [..payee.Synonymous, synonym]
        };

        dbContext.Payees.Remove(payee);
        dbContext.Payees.Add(updatedPayee);

        await dbContext.SaveChangesAsync(cancellationToken);
        Console.WriteLine($"Added synonym '{synonym}' to payee '{name}'.");
        return 0;
    }
}
