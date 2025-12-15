using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using System.Text.Json;

namespace Smoothment.Database;

/// <summary>
///     Represents a payee in the database.
///     A payee can be associated with both expense and top-up transactions.
///     It includes properties for the payee's name, descriptions, categories, and synonymous names.
///     The SynonymousJson property is used to serialize and deserialize the synonymous names to/from JSON.
///     The class is mapped to the "Payees" table in the database.
///     The Name property is required and serves as the primary key.
/// </summary>
[Table("Payees")]
public class Payee
{
    [Key] [Required] public required string Name { get; init; }

    public string? ExpenseDescription { get; init; }

    public string? ExpenseCategory { get; init; }

    public string? TopUpDescription { get; init; }

    public string? TopUpCategory { get; init; }

    [NotMapped] public required string[] Synonymous { get; init; } = [];

    public string? SynonymousJson
    {
        get => JsonSerializer.Serialize(Synonymous);
        init
        {
            if (!string.IsNullOrEmpty(value)) Synonymous = JsonSerializer.Deserialize<string[]>(value) ?? [];
        }
    }
}
