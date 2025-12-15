using Smoothment.Converters;
using Smoothment.Database;
using Microsoft.EntityFrameworkCore;

namespace Smoothment.Services;

public class TransactionEnricher(SmoothmentDbContext dbContext) : ITransactionEnricher
{
    public async Task<IReadOnlyCollection<Transaction>> EnrichAsync(
        IReadOnlyCollection<Transaction> transactions,
        CancellationToken cancellationToken)
    {
        var payees = await dbContext.Payees.AsNoTracking().ToListAsync(cancellationToken);
        var categories = await dbContext.Categories.AsNoTracking().ToListAsync(cancellationToken);

        var payeeDict = BuildPayeeDictionary(payees);
        var categoryDict = BuildCategoryDictionary(categories);

        return transactions.Select(t => EnrichTransaction(t, payeeDict, categoryDict)).ToList();
    }

    private static Dictionary<string, Payee> BuildPayeeDictionary(IEnumerable<Payee> payees)
    {
        return payees
            .SelectMany(p => new[] { p.Name }.Concat(p.Synonymous), (p, name) => (name, payee: p))
            .GroupBy(x => x.name, StringComparer.InvariantCultureIgnoreCase)
            .ToDictionary(g => g.Key, g => g.First().payee, StringComparer.InvariantCultureIgnoreCase);
    }

    private static Dictionary<string, Category> BuildCategoryDictionary(IEnumerable<Category> categories)
    {
        return categories
            .SelectMany(c => new[] { c.Name }.Concat(c.Synonymous), (c, name) => (name, category: c))
            .Where(x => !string.IsNullOrEmpty(x.name))
            .GroupBy(x => x.name!, StringComparer.InvariantCultureIgnoreCase)
            .ToDictionary(g => g.Key, g => g.First().category, StringComparer.InvariantCultureIgnoreCase);
    }

    private static Transaction EnrichTransaction(
        Transaction transaction,
        IReadOnlyDictionary<string, Payee> payeeDict,
        IReadOnlyDictionary<string, Category> categoryDict)
    {
        if (payeeDict.TryGetValue(transaction.Payee, out var matchingPayee))
            return transaction with
            {
                Payee = matchingPayee.Name,
                Category = transaction.Type is TransactionType.Expense
                    ? matchingPayee.ExpenseCategory
                    : matchingPayee.TopUpCategory,
                Description = transaction.Type is TransactionType.Expense
                    ? matchingPayee.ExpenseDescription
                    : matchingPayee.TopUpDescription
            };

        if (transaction.Category != null && categoryDict.TryGetValue(transaction.Category, out var matchingCategory))
            return transaction with { Category = matchingCategory.Name };

        return transaction;
    }
}
