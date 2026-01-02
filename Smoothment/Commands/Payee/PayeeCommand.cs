using System.CommandLine;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Smoothment.Database;

namespace Smoothment.Commands.Payee;

public static class PayeeCommand
{
    public static Command Create(IServiceProvider serviceProvider)
    {
        var command = new Command("payee",
            """
            Manage payees in the database.

            Payees are used to enrich transactions with category and description
            information. Each payee can have synonyms for matching alternative names.

            Examples:
              smoothment payee                                  # list all
              smoothment payee add "Starbucks"                  # add
              smoothment payee remove "Starbucks"               # remove
              smoothment payee synonym "Starbucks" "SBUX"       # add synonym
            """);

        command.Subcommands.Add(CreateListCommand(serviceProvider));
        command.Subcommands.Add(CreateAddCommand(serviceProvider));
        command.Subcommands.Add(CreateRemoveCommand(serviceProvider));
        command.Subcommands.Add(CreateSynonymCommand(serviceProvider));

        // Default action: list payees
        command.SetAction(async (_, cancellationToken) =>
        {
            using var scope = serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();

            var payees = await db.Payees
                .OrderBy(p => p.Name)
                .ToListAsync(cancellationToken);

            if (payees.Count == 0)
            {
                Console.WriteLine("No payees found.");
                return 0;
            }

            Console.WriteLine($"Payees ({payees.Count}):");
            foreach (var payee in payees)
            {
                Console.WriteLine($"  {payee.Name}");
                if (payee.ExpenseCategory is not null)
                    Console.WriteLine($"    Expense: {payee.ExpenseCategory} - {payee.ExpenseDescription}");
                if (payee.TopUpCategory is not null)
                    Console.WriteLine($"    TopUp: {payee.TopUpCategory} - {payee.TopUpDescription}");
                if (payee.Synonymous.Length > 0)
                    Console.WriteLine($"    Synonyms: {string.Join(", ", payee.Synonymous)}");
            }

            return 0;
        });

        return command;
    }

    private static Command CreateListCommand(IServiceProvider serviceProvider)
    {
        var command = new Command("list", "List all payees in the database");

        command.SetAction(async (_, cancellationToken) =>
        {
            using var scope = serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();

            var payees = await db.Payees
                .OrderBy(p => p.Name)
                .ToListAsync(cancellationToken);

            if (payees.Count == 0)
            {
                Console.WriteLine("No payees found.");
                return 0;
            }

            Console.WriteLine($"Payees ({payees.Count}):");
            foreach (var payee in payees)
            {
                Console.WriteLine($"  {payee.Name}");
                if (payee.ExpenseCategory is not null)
                    Console.WriteLine($"    Expense: {payee.ExpenseCategory} - {payee.ExpenseDescription}");
                if (payee.TopUpCategory is not null)
                    Console.WriteLine($"    TopUp: {payee.TopUpCategory} - {payee.TopUpDescription}");
                if (payee.Synonymous.Length > 0)
                    Console.WriteLine($"    Synonyms: {string.Join(", ", payee.Synonymous)}");
            }

            return 0;
        });

        return command;
    }

    private static Command CreateAddCommand(IServiceProvider serviceProvider)
    {
        var nameArg = new Argument<string>("name", "Name of the payee to add");

        var expenseCategoryOption = new Option<string?>("--expense-category")
        {
            Description = "Category for expense transactions"
        };

        var expenseDescriptionOption = new Option<string?>("--expense-description")
        {
            Description = "Description for expense transactions"
        };

        var topUpCategoryOption = new Option<string?>("--topup-category")
        {
            Description = "Category for top-up transactions"
        };

        var topUpDescriptionOption = new Option<string?>("--topup-description")
        {
            Description = "Description for top-up transactions"
        };

        var command = new Command("add", "Add a new payee to the database")
        {
            nameArg,
            expenseCategoryOption,
            expenseDescriptionOption,
            topUpCategoryOption,
            topUpDescriptionOption
        };

        command.SetAction(async (parseResult, cancellationToken) =>
        {
            var name = parseResult.GetValue(nameArg)!;
            var expenseCategory = parseResult.GetValue(expenseCategoryOption);
            var expenseDescription = parseResult.GetValue(expenseDescriptionOption);
            var topUpCategory = parseResult.GetValue(topUpCategoryOption);
            var topUpDescription = parseResult.GetValue(topUpDescriptionOption);

            using var scope = serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();

            var existing = await db.Payees
                .FirstOrDefaultAsync(p => p.Name == name, cancellationToken);

            if (existing is not null)
            {
                Console.WriteLine($"Payee '{name}' already exists.");
                return 1;
            }

            db.Payees.Add(new Database.Payee
            {
                Name = name,
                ExpenseCategory = expenseCategory,
                ExpenseDescription = expenseDescription,
                TopUpCategory = topUpCategory,
                TopUpDescription = topUpDescription,
                Synonymous = []
            });
            await db.SaveChangesAsync(cancellationToken);

            Console.WriteLine($"Added payee '{name}'.");
            return 0;
        });

        return command;
    }

    private static Command CreateRemoveCommand(IServiceProvider serviceProvider)
    {
        var nameArg = new Argument<string>("name", "Name of the payee to remove");

        var command = new Command("remove", "Remove a payee from the database")
        {
            nameArg
        };

        command.SetAction(async (parseResult, cancellationToken) =>
        {
            var name = parseResult.GetValue(nameArg)!;

            using var scope = serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();

            var payee = await db.Payees
                .FirstOrDefaultAsync(p => p.Name == name, cancellationToken);

            if (payee is null)
            {
                Console.WriteLine($"Payee '{name}' not found.");
                return 1;
            }

            db.Payees.Remove(payee);
            await db.SaveChangesAsync(cancellationToken);

            Console.WriteLine($"Removed payee '{name}'.");
            return 0;
        });

        return command;
    }

    private static Command CreateSynonymCommand(IServiceProvider serviceProvider)
    {
        var nameArg = new Argument<string>("name", "Name of the payee");
        var synonymArg = new Argument<string>("synonym", "The synonym to add");

        var command = new Command("synonym", "Add a synonym to a payee")
        {
            nameArg,
            synonymArg
        };

        command.SetAction(async (parseResult, cancellationToken) =>
        {
            var name = parseResult.GetValue(nameArg)!;
            var synonym = parseResult.GetValue(synonymArg)!;

            using var scope = serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();

            var payee = await db.Payees
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
            var updatedPayee = new Database.Payee
            {
                Name = payee.Name,
                ExpenseDescription = payee.ExpenseDescription,
                ExpenseCategory = payee.ExpenseCategory,
                TopUpDescription = payee.TopUpDescription,
                TopUpCategory = payee.TopUpCategory,
                Synonymous = [..payee.Synonymous, synonym]
            };

            db.Payees.Remove(payee);
            db.Payees.Add(updatedPayee);
            await db.SaveChangesAsync(cancellationToken);

            Console.WriteLine($"Added synonym '{synonym}' to payee '{name}'.");
            return 0;
        });

        return command;
    }
}
