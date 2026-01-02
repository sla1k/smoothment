using System.CommandLine;
using Microsoft.Extensions.DependencyInjection;

namespace Smoothment.Commands.Synonym;

public static class SynonymCommand
{
    public static Command Create(IServiceProvider serviceProvider)
    {
        var typeOption = new Option<string>("--type")
        {
            Description =
                """
                The type of entity to add the synonym to:
                  - category: Add synonym to a category
                  - payee: Add synonym to a payee
                """,
            Required = true
        };
        typeOption.AcceptOnlyFromAmong("category", "payee");

        var nameOption = new Option<string>("--name")
        {
            Description = "The name of the category or payee to add the synonym to",
            Required = true
        };

        var synonymOption = new Option<string>("--synonym")
        {
            Description = "The synonym to add",
            Required = true
        };

        var command = new Command("synonym",
            """
            Add a synonym to a category or payee in the database.

            Synonyms allow transaction enrichment to match alternative names
            to the canonical category or payee name.

            Examples:
              smoothment synonym --type=category --name="Groceries" --synonym="supermarket"
              smoothment synonym --type=payee --name="Starbucks" --synonym="STARBUCKS CORP"
            """)
        {
            typeOption,
            nameOption,
            synonymOption
        };

        command.SetAction(async (parseResult, cancellationToken) =>
        {
            var type = parseResult.GetValue(typeOption)!.ToLowerInvariant();
            var name = parseResult.GetValue(nameOption)!;
            var synonym = parseResult.GetValue(synonymOption)!;

            using var scope = serviceProvider.CreateScope();
            var handler = scope.ServiceProvider.GetRequiredService<ICommandHandler<SynonymCommandOptions>>();

            var options = new SynonymCommandOptions(type, name, synonym);
            return await handler.ExecuteAsync(options, cancellationToken);
        });

        return command;
    }
}
