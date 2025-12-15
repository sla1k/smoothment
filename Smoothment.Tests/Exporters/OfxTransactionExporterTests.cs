using System.Text.RegularExpressions;
using System.Xml;
using Smoothment.Converters;
using Smoothment.Exporters;

namespace Smoothment.Tests.Exporters;

public class OfxTransactionExporterTests
{
    [Fact]
    public void Key_ReturnsCorrectValue()
    {
        var exporter = new OfxTransactionExporter();

        Assert.Equal("ofx", exporter.Key);
    }

    [Fact]
    public void FileExtension_ReturnsCorrectValue()
    {
        var exporter = new OfxTransactionExporter();

        Assert.Equal(".ofx", exporter.FileExtension);
    }

    [Fact]
    public async Task ExportAsync_EmptyTransactions_ThrowsArgumentException()
    {
        var exporter = new OfxTransactionExporter();
        var transactions = new List<Transaction>();
        var tempFile = Path.GetTempFileName();

        try
        {
            var exception = await Assert.ThrowsAsync<ArgumentException>(() =>
                exporter.ExportAsync(transactions, tempFile, CancellationToken.None));
            Assert.Equal("transactions", exception.ParamName);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_SingleTransaction_WritesCorrectly()
    {
        var exporter = new OfxTransactionExporter();
        var transaction = new Transaction
        {
            Bank = "tbank",
            Account = "checking",
            Payee = "Test Payee",
            Amount = -100.50m,
            Category = "Food",
            Description = "Test Description",
            Date = new DateTime(2025, 10, 11, 14, 30, 45),
            Currency = "USD",
            IsTransfer = false
        };
        var transactions = new List<Transaction> { transaction };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);

            // Verify transaction data
            Assert.Contains("<CURDEF>USD</CURDEF>", content);
            Assert.Contains("<BANKID>tbank</BANKID>", content);
            Assert.Contains("<ACCTID>checking</ACCTID>", content);
            Assert.Contains("<TRNTYPE>DEBIT</TRNTYPE>", content);
            Assert.Contains("<TRNAMT>-100.50</TRNAMT>", content);
            Assert.Contains("<NAME>Test Payee</NAME>", content);
            Assert.Contains("<MEMO>Test Description</MEMO>", content);
            Assert.Contains("<DTPOSTED>20251011143045</DTPOSTED>", content);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_MultipleTransactionsSameAccount_GroupsCorrectly()
    {
        var exporter = new OfxTransactionExporter();
        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Payee 1",
                Amount = -50.00m,
                Category = "Food",
                Description = "Desc 1",
                Date = new DateTime(2025, 10, 1, 10, 0, 0),
                Currency = "USD",
                IsTransfer = false
            },
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Payee 2",
                Amount = -30.00m,
                Category = "Transport",
                Description = "Desc 2",
                Date = new DateTime(2025, 10, 5, 15, 30, 0),
                Currency = "USD",
                IsTransfer = false
            }
        };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);

            // Verify both transactions are in the same statement
            Assert.Contains("<NAME>Payee 1</NAME>", content);
            Assert.Contains("<NAME>Payee 2</NAME>", content);
            Assert.Contains("<DTSTART>20251001</DTSTART>", content);
            Assert.Contains("<DTEND>20251005</DTEND>", content);

            // Verify ledger balance (sum of transactions)
            Assert.Contains("<BALAMT>-80.00</BALAMT>", content);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_MultipleAccounts_CreatesSeparateStatements()
    {
        var exporter = new OfxTransactionExporter();
        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Payee 1",
                Amount = -50.00m,
                Category = "Food",
                Description = "Desc 1",
                Date = new DateTime(2025, 10, 1),
                Currency = "USD",
                IsTransfer = false
            },
            new()
            {
                Bank = "tbank",
                Account = "savings",
                Payee = "Payee 2",
                Amount = 100.00m,
                Category = "Income",
                Description = "Desc 2",
                Date = new DateTime(2025, 10, 2),
                Currency = "USD",
                IsTransfer = false
            }
        };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);

            // Verify both accounts are present
            var checkingCount = Regex.Matches(content, "<ACCTID>checking</ACCTID>").Count;
            var savingsCount = Regex.Matches(content, "<ACCTID>savings</ACCTID>").Count;

            Assert.Equal(1, checkingCount);
            Assert.Equal(1, savingsCount);

            // Verify two separate statements
            var stmtTrnrsCount = Regex.Matches(content, "<STMTTRNRS>").Count;
            Assert.Equal(2, stmtTrnrsCount);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_TransferTransaction_UsesXferType()
    {
        var exporter = new OfxTransactionExporter();
        var transaction = new Transaction
        {
            Bank = "tbank",
            Account = "checking",
            Payee = "Transfer",
            Amount = -100.00m,
            Category = "Transfer",
            Description = "Account transfer",
            Date = new DateTime(2025, 10, 11),
            Currency = "USD",
            IsTransfer = true
        };
        var transactions = new List<Transaction> { transaction };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);

            // Verify transfer type
            Assert.Contains("<TRNTYPE>XFER</TRNTYPE>", content);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_PositiveAmount_UsesCreditType()
    {
        var exporter = new OfxTransactionExporter();
        var transaction = new Transaction
        {
            Bank = "tbank",
            Account = "checking",
            Payee = "Salary",
            Amount = 5000.00m,
            Category = "Income",
            Description = "Monthly salary",
            Date = new DateTime(2025, 10, 1),
            Currency = "USD",
            IsTransfer = false
        };
        var transactions = new List<Transaction> { transaction };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);

            // Verify credit type for positive amount
            Assert.Contains("<TRNTYPE>CREDIT</TRNTYPE>", content);
            Assert.Contains("<TRNAMT>5000.00</TRNAMT>", content);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_TransactionWithoutDescription_OmitsMemoField()
    {
        var exporter = new OfxTransactionExporter();
        var transaction = new Transaction
        {
            Bank = "tbank",
            Account = "checking",
            Payee = "Test Payee",
            Amount = -50.00m,
            Category = "Food",
            Description = null,
            Date = new DateTime(2025, 10, 11),
            Currency = "USD",
            IsTransfer = false
        };
        var transactions = new List<Transaction> { transaction };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);

            // Verify MEMO field is not present
            Assert.DoesNotContain("<MEMO>", content);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_MultipleCurrencies_CreatesSeparateStatements()
    {
        var exporter = new OfxTransactionExporter();
        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Payee 1",
                Amount = -50.00m,
                Category = "Food",
                Description = "USD transaction",
                Date = new DateTime(2025, 10, 1),
                Currency = "USD",
                IsTransfer = false
            },
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Payee 2",
                Amount = -30.00m,
                Category = "Food",
                Description = "EUR transaction",
                Date = new DateTime(2025, 10, 2),
                Currency = "EUR",
                IsTransfer = false
            }
        };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);

            // Verify both currencies are present in separate statements
            Assert.Contains("<CURDEF>USD</CURDEF>", content);
            Assert.Contains("<CURDEF>EUR</CURDEF>", content);

            // Verify two separate statements (same bank/account but different currency)
            var stmtTrnrsCount = Regex.Matches(content, "<STMTTRNRS>").Count;
            Assert.Equal(2, stmtTrnrsCount);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_ValidatesOfxStructure()
    {
        var exporter = new OfxTransactionExporter();
        var transaction = new Transaction
        {
            Bank = "tbank",
            Account = "checking",
            Payee = "Test",
            Amount = -100.00m,
            Category = "Food",
            Description = "Test",
            Date = new DateTime(2025, 10, 11),
            Currency = "USD",
            IsTransfer = false
        };
        var transactions = new List<Transaction> { transaction };

        // Create temp file with .ofx extension
        var tempDir = Path.GetTempPath();
        var tempFileName = $"test_{Guid.NewGuid()}.ofx";
        var tempFile = Path.Combine(tempDir, tempFileName);

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            // Verify file has .ofx extension
            Assert.Equal(".ofx", Path.GetExtension(tempFile));

            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);

            // Split header and XML body
            var parts = content.Split(new[] { "\r\n\r\n", "\n\n" }, StringSplitOptions.None);
            Assert.True(parts.Length >= 2, "OFX should have header and body sections");

            // Verify XML is well-formed by parsing it
            var xmlContent = parts[1];
            var doc = new XmlDocument();
            doc.LoadXml(xmlContent); // This will throw if XML is malformed

            // Verify root element
            Assert.Equal("OFX", doc.DocumentElement?.Name);
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_GeneratesUniqueTransactionIds()
    {
        var exporter = new OfxTransactionExporter();
        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Payee 1",
                Amount = -50.00m,
                Category = "Food",
                Description = "Desc 1",
                Date = new DateTime(2025, 10, 1, 10, 0, 0),
                Currency = "USD",
                IsTransfer = false
            },
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Payee 2",
                Amount = -50.00m, // Same amount
                Category = "Food",
                Description = "Desc 2",
                Date = new DateTime(2025, 10, 1, 15, 0, 0), // Different time
                Currency = "USD",
                IsTransfer = false
            }
        };
        var tempFile = Path.GetTempFileName();

        try
        {
            await exporter.ExportAsync(transactions, tempFile, CancellationToken.None);

            var content = await File.ReadAllTextAsync(tempFile, CancellationToken.None);

            // Extract all FITID values
            var fitidPattern = new Regex(@"<FITID>([^<]+)</FITID>");
            var matches = fitidPattern.Matches(content);
            var fitIds = matches.Select(m => m.Groups[1].Value).ToList();

            // Verify we have transaction IDs and they are unique
            Assert.Equal(2, fitIds.Count);
            Assert.Equal(fitIds.Count, fitIds.Distinct().Count());
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ExportAsync_CancellationRequested_ThrowsOperationCanceledException()
    {
        var exporter = new OfxTransactionExporter();
        var transactions = new List<Transaction>
        {
            new()
            {
                Bank = "tbank",
                Account = "checking",
                Payee = "Test",
                Amount = -100m,
                Category = "Food",
                Description = "Test",
                Date = DateTime.Now,
                Currency = "USD",
                IsTransfer = false
            }
        };
        var tempFile = Path.GetTempFileName();
        var cts = new CancellationTokenSource();
        cts.Cancel();

        try
        {
            await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
                await exporter.ExportAsync(transactions, tempFile, cts.Token)
            );
        }
        finally
        {
            if (File.Exists(tempFile))
                File.Delete(tempFile);
        }
    }
}
