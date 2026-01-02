using System.CommandLine;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Smoothment.Database;

namespace Smoothment.Commands.Category;

public static class CategoryCommand
{
    public static Command Create(IServiceProvider serviceProvider)
    {
        var command = new Command("category",
            """
            Manage categories in the database.

            Categories are used to classify transactions during enrichment.
            Each category can have synonyms for matching alternative names.

            Examples:
              smoothment category                              # list all
              smoothment category add "Groceries"              # add
              smoothment category remove "Groceries"           # remove
              smoothment category synonym "Groceries" "food"   # add synonym
            """);

        command.Subcommands.Add(CreateListCommand(serviceProvider));
        command.Subcommands.Add(CreateAddCommand(serviceProvider));
        command.Subcommands.Add(CreateRemoveCommand(serviceProvider));
        command.Subcommands.Add(CreateSynonymCommand(serviceProvider));

        // Default action: list categories
        command.SetAction(async (_, cancellationToken) =>
        {
            using var scope = serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();

            var categories = await db.Categories
                .OrderBy(c => c.Name)
                .ToListAsync(cancellationToken);

            if (categories.Count == 0)
            {
                Console.WriteLine("No categories found.");
                return 0;
            }

            Console.WriteLine($"Categories ({categories.Count}):");
            foreach (var category in categories)
            {
                Console.WriteLine($"  {category.Name}");
                if (category.Synonymous.Length > 0)
                {
                    Console.WriteLine($"    Synonyms: {string.Join(", ", category.Synonymous)}");
                }
            }

            return 0;
        });

        return command;
    }

    private static Command CreateListCommand(IServiceProvider serviceProvider)
    {
        var command = new Command("list", "List all categories in the database");

        command.SetAction(async (_, cancellationToken) =>
        {
            using var scope = serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();

            var categories = await db.Categories
                .OrderBy(c => c.Name)
                .ToListAsync(cancellationToken);

            if (categories.Count == 0)
            {
                Console.WriteLine("No categories found.");
                return 0;
            }

            Console.WriteLine($"Categories ({categories.Count}):");
            foreach (var category in categories)
            {
                Console.WriteLine($"  {category.Name}");
                if (category.Synonymous.Length > 0)
                {
                    Console.WriteLine($"    Synonyms: {string.Join(", ", category.Synonymous)}");
                }
            }

            return 0;
        });

        return command;
    }

    private static Command CreateAddCommand(IServiceProvider serviceProvider)
    {
        var nameArg = new Argument<string>("name", "Name of the category to add");

        var command = new Command("add", "Add a new category to the database")
        {
            nameArg
        };

        command.SetAction(async (parseResult, cancellationToken) =>
        {
            var name = parseResult.GetValue(nameArg)!;

            using var scope = serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();

            var existing = await db.Categories
                .FirstOrDefaultAsync(c => c.Name == name, cancellationToken);

            if (existing is not null)
            {
                Console.WriteLine($"Category '{name}' already exists.");
                return 1;
            }

            db.Categories.Add(new Database.Category { Name = name });
            await db.SaveChangesAsync(cancellationToken);

            Console.WriteLine($"Added category '{name}'.");
            return 0;
        });

        return command;
    }

    private static Command CreateRemoveCommand(IServiceProvider serviceProvider)
    {
        var nameArg = new Argument<string>("name", "Name of the category to remove");

        var command = new Command("remove", "Remove a category from the database")
        {
            nameArg
        };

        command.SetAction(async (parseResult, cancellationToken) =>
        {
            var name = parseResult.GetValue(nameArg)!;

            using var scope = serviceProvider.CreateScope();
            var db = scope.ServiceProvider.GetRequiredService<SmoothmentDbContext>();

            var category = await db.Categories
                .FirstOrDefaultAsync(c => c.Name == name, cancellationToken);

            if (category is null)
            {
                Console.WriteLine($"Category '{name}' not found.");
                return 1;
            }

            db.Categories.Remove(category);
            await db.SaveChangesAsync(cancellationToken);

            Console.WriteLine($"Removed category '{name}'.");
            return 0;
        });

        return command;
    }

    private static Command CreateSynonymCommand(IServiceProvider serviceProvider)
    {
        var nameArg = new Argument<string>("name", "Name of the category");
        var synonymArg = new Argument<string>("synonym", "The synonym to add");

        var command = new Command("synonym", "Add a synonym to a category")
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

            var category = await db.Categories
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
            await db.SaveChangesAsync(cancellationToken);

            Console.WriteLine($"Added synonym '{synonym}' to category '{name}'.");
            return 0;
        });

        return command;
    }
}
