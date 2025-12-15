namespace Smoothment.Converters;

/// <summary>
///     Transaction model
/// </summary>
public record Transaction
{
    /// <summary>
    ///     Bank name/identifier
    /// </summary>
    public required string Bank { get; init; }

    /// <summary>
    ///     Account of the transaction
    /// </summary>
    public required string Account { get; init; }

    /// <summary>
    ///     Payee of the transaction
    /// </summary>
    public required string Payee { get; init; }

    /// <summary>
    ///     Amount of the transaction
    /// </summary>
    public required decimal Amount { get; init; }

    /// <summary>
    ///     Category of the transaction
    /// </summary>
    public required string? Category { get; init; }

    /// <summary>
    ///     Description of the transaction
    /// </summary>
    public required string? Description { get; init; }

    /// <summary>
    ///     Transaction Date
    /// </summary>
    public required DateTimeOffset Date { get; init; }

    /// <summary>
    ///     Currency code (ISO 4217, e.g., USD, EUR, GBP)
    /// </summary>
    public required string Currency { get; init; }

    /// <summary>
    ///     Transaction Type
    /// </summary>
    public TransactionType Type => Amount >= 0 ? TransactionType.TopUp : TransactionType.Expense;

    /// <summary>
    ///     Whether this transaction is a transfer between accounts
    /// </summary>
    public bool IsTransfer { get; init; }
}
