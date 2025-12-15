using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using System.Text.Json;

namespace Smoothment.Database;

/// <summary>
///     Represents a category in the database.
///     Categories can be used to classify transactions.
///     The SynonymousJson property is used to serialize and deserialize synonymous names to/from JSON.
///     The class is mapped to the "Categories" table in the database.
///     The Name property is required and serves as the primary key.
/// </summary>
[Table("Categories")]
public class Category
{
    [Key] [Required] public required string Name { get; init; }

    [NotMapped] public string[] Synonymous { get; set; } = [];

    public string? SynonymousJson
    {
        get => JsonSerializer.Serialize(Synonymous);
        init
        {
            if (!string.IsNullOrEmpty(value))
            {
                Synonymous = JsonSerializer.Deserialize<string[]>(value) ?? [];
            }
        }
    }
}
