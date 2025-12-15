using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Xml;
using Smoothment.Converters;

namespace Smoothment.Exporters;

/// <summary>
///     OFX (Open Financial Exchange) transaction exporter
///     Generates OFX version 1.0.2 (SGML) format files
/// </summary>
public class OfxTransactionExporter : ITransactionExporter
{
    public string Key => "ofx";
    public string FileExtension => ".ofx";

    public async Task ExportAsync(IReadOnlyCollection<Transaction> transactions, string outputPath,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(transactions);
        if (transactions.Count == 0)
            throw new ArgumentException("Transaction collection cannot be empty.", nameof(transactions));

        var ofxContent = GenerateOfxContent(transactions);
        await File.WriteAllTextAsync(outputPath, ofxContent, Encoding.UTF8, cancellationToken);
    }

    private string GenerateOfxContent(IReadOnlyCollection<Transaction> transactions)
    {
        var sb = new StringBuilder();

        WriteOfxHeader(sb);
        WriteOfxBody(transactions, sb);

        return sb.ToString();
    }

    /// <summary>
    ///     Write OFX header (SGML format requires plain text header, not XML)
    /// </summary>
    private void WriteOfxHeader(StringBuilder sb)
    {
        // OFXHEADER: OFX specification version (100 = 1.0)
        sb.AppendLine("OFXHEADER:100");
        // DATA: Format type (OFXSGML for version 1.x, XML for version 2.x)
        sb.AppendLine("DATA:OFXSGML");
        // VERSION: OFX version number (102 = 1.0.2)
        sb.AppendLine("VERSION:102");
        // SECURITY: Security level (NONE, TYPE1)
        sb.AppendLine("SECURITY:NONE");
        // ENCODING: Character encoding (USASCII, UNICODE, UTF-8)
        sb.AppendLine("ENCODING:UTF-8");
        // CHARSET: Character set (NONE for UTF-8, 1252 for Windows-1252)
        sb.AppendLine("CHARSET:NONE");
        // COMPRESSION: Compression method (NONE)
        sb.AppendLine("COMPRESSION:NONE");
        // OLDFILEUID: Previous file UID for tracking (NONE for new files)
        sb.AppendLine("OLDFILEUID:NONE");
        // NEWFILEUID: Current file UID (NONE if not tracking)
        sb.AppendLine("NEWFILEUID:NONE");
        sb.AppendLine();
    }

    /// <summary>
    ///     Write OFX XML body
    /// </summary>
    private void WriteOfxBody(IReadOnlyCollection<Transaction> transactions, StringBuilder sb)
    {
        // XML Body - configure writer settings for proper formatting
        var settings = new XmlWriterSettings
        {
            Indent = true, // Enable indentation for readability
            IndentChars = "  ", // Use 2 spaces for indentation
            OmitXmlDeclaration = true, // Skip <?xml?> declaration (OFX SGML doesn't use it)
            Encoding = Encoding.UTF8
        };

        using var stringWriter = new StringWriter(sb);
        using var writer = XmlWriter.Create(stringWriter, settings);

        // OFX root element - main container for all OFX data
        writer.WriteStartElement("OFX");

        WriteSignOnMessage(writer);
        WriteBankMessages(writer, transactions);

        writer.WriteEndElement(); // OFX
        writer.Flush();
    }

    /// <summary>
    ///     Write sign-on message response (SIGNONMSGSRSV1)
    ///     Contains authentication and session information
    /// </summary>
    private void WriteSignOnMessage(XmlWriter writer)
    {
        writer.WriteStartElement("SIGNONMSGSRSV1");
        writer.WriteStartElement("SONRS");

        // STATUS: Response status indicator
        writer.WriteStartElement("STATUS");
        // CODE: Status code (0 = success, non-zero = error)
        writer.WriteElementString("CODE", "0");
        // SEVERITY: Error severity (INFO, WARN, ERROR)
        writer.WriteElementString("SEVERITY", "INFO");
        writer.WriteEndElement(); // STATUS

        // DTSERVER: Server date/time in format YYYYMMDDhhmmss
        writer.WriteElementString("DTSERVER", DateTimeOffset.Now.ToString("yyyyMMddHHmmss"));
        // LANGUAGE: Language code (ENG, FRA, SPA, etc.)
        writer.WriteElementString("LANGUAGE", "ENG");

        writer.WriteEndElement(); // SONRS
        writer.WriteEndElement(); // SIGNONMSGSRSV1
    }

    /// <summary>
    ///     Write bank message set response (BANKMSGSRSV1)
    ///     Contains all banking transaction data grouped by bank, account, and currency
    /// </summary>
    private void WriteBankMessages(XmlWriter writer, IReadOnlyCollection<Transaction> transactions)
    {
        writer.WriteStartElement("BANKMSGSRSV1");

        var transactionGroups = transactions
            .GroupBy(t => new { t.Bank, t.Account, t.Currency });

        foreach (var group in transactionGroups) WriteAccountStatement(writer, group);

        writer.WriteEndElement(); // BANKMSGSRSV1
    }

    /// <summary>
    ///     Write statement for a single bank account with specific currency
    /// </summary>
    private void WriteAccountStatement(XmlWriter writer, IGrouping<dynamic, Transaction> accountGroup)
    {
        var accountTransactions = accountGroup.OrderBy(t => t.Date).ToList();
        var startDate = accountTransactions.First().Date;
        var endDate = accountTransactions.Last().Date;

        // STMTTRNRS: Statement transaction response wrapper
        writer.WriteStartElement("STMTTRNRS");
        // TRNUID: Transaction unique ID (can be any unique string)
        writer.WriteElementString("TRNUID", "1");

        // STATUS: Statement request status
        writer.WriteStartElement("STATUS");
        writer.WriteElementString("CODE", "0");
        writer.WriteElementString("SEVERITY", "INFO");
        writer.WriteEndElement(); // STATUS

        // STMTRS: Statement response - contains account and transaction data
        writer.WriteStartElement("STMTRS");
        // CURDEF: Currency definition (USD, EUR, GBP, etc. - ISO 4217 codes)
        writer.WriteElementString("CURDEF", accountGroup.Key.Currency);

        WriteAccountInfo(writer, accountGroup.Key.Bank, accountGroup.Key.Account);
        WriteTransactionList(writer, accountTransactions, startDate, endDate);
        WriteLedgerBalance(writer, accountTransactions, endDate);

        writer.WriteEndElement(); // STMTRS
        writer.WriteEndElement(); // STMTTRNRS
    }

    /// <summary>
    ///     Write bank account information (BANKACCTFROM)
    /// </summary>
    private void WriteAccountInfo(XmlWriter writer, string bankId, string accountId)
    {
        writer.WriteStartElement("BANKACCTFROM");
        // BANKID: Bank routing number or identifier (using bank name/key as identifier)
        writer.WriteElementString("BANKID", bankId);
        // ACCTID: Account number/identifier
        writer.WriteElementString("ACCTID", accountId);
        // ACCTTYPE: Account type (CHECKING, SAVINGS, MONEYMRKT, CREDITLINE)
        writer.WriteElementString("ACCTTYPE", "CHECKING");
        writer.WriteEndElement(); // BANKACCTFROM
    }

    /// <summary>
    ///     Write list of bank transactions (BANKTRANLIST)
    /// </summary>
    private void WriteTransactionList(XmlWriter writer, List<Transaction> accountTransactions, DateTimeOffset startDate,
        DateTimeOffset endDate)
    {
        writer.WriteStartElement("BANKTRANLIST");
        // DTSTART: Start date of statement period (YYYYMMDD)
        writer.WriteElementString("DTSTART", startDate.ToString("yyyyMMdd"));
        // DTEND: End date of statement period (YYYYMMDD)
        writer.WriteElementString("DTEND", endDate.ToString("yyyyMMdd"));

        foreach (var transaction in accountTransactions) WriteTransaction(writer, transaction);

        writer.WriteEndElement(); // BANKTRANLIST
    }

    /// <summary>
    ///     Write individual transaction (STMTTRN)
    /// </summary>
    private void WriteTransaction(XmlWriter writer, Transaction transaction)
    {
        writer.WriteStartElement("STMTTRN");
        // TRNTYPE: Transaction type (DEBIT, CREDIT, INT, DIV, FEE, SRVCHG, DEP, ATM, POS, XFER, CHECK, PAYMENT, CASH, DIRECTDEP, DIRECTDEBIT, REPEATPMT, OTHER)
        var transactionType = transaction.IsTransfer ? "XFER" :
            transaction.Type == TransactionType.Expense ? "DEBIT" : "CREDIT";
        writer.WriteElementString("TRNTYPE", transactionType);
        // DTPOSTED: Date transaction was posted (YYYYMMDD or YYYYMMDDhhmmss)
        writer.WriteElementString("DTPOSTED", transaction.Date.ToString("yyyyMMddHHmmss"));
        // TRNAMT: Transaction amount (negative for debits, positive for credits)
        writer.WriteElementString("TRNAMT", transaction.Amount.ToString("F2", CultureInfo.InvariantCulture));
        // FITID: Financial institution transaction ID (must be unique per account)
        writer.WriteElementString("FITID", GenerateTransactionId(transaction));
        // NAME: Payee name or transaction description (up to 32 chars recommended)
        writer.WriteElementString("NAME", transaction.Payee);

        // MEMO: Additional transaction information (optional, up to 255 chars)
        if (!string.IsNullOrEmpty(transaction.Description)) writer.WriteElementString("MEMO", transaction.Description);

        writer.WriteEndElement(); // STMTTRN
    }

    /// <summary>
    ///     Write ledger balance (LEDGERBAL)
    /// </summary>
    private void WriteLedgerBalance(XmlWriter writer, List<Transaction> accountTransactions, DateTimeOffset endDate)
    {
        writer.WriteStartElement("LEDGERBAL");
        // BALAMT: Balance amount
        writer.WriteElementString("BALAMT",
            accountTransactions.Sum(t => t.Amount).ToString("F2", CultureInfo.InvariantCulture));
        // DTASOF: Date of balance (YYYYMMDD)
        writer.WriteElementString("DTASOF", endDate.ToString("yyyyMMdd"));
        writer.WriteEndElement(); // LEDGERBAL
    }

    /// <summary>
    ///     Generate a unique transaction ID based on transaction details
    ///     Uses SHA256 hash to ensure same transaction always gets same ID
    ///     Includes date and time to differentiate transactions that occur at different times
    /// </summary>
    private string GenerateTransactionId(Transaction transaction)
    {
        // Include full date-time (including hours, minutes, seconds) to differentiate similar transactions
        var idSource =
            $"{transaction.Bank}|{transaction.Account}|{transaction.Date:yyyyMMddHHmmss}|{transaction.Payee}|{transaction.Amount:F2}|{transaction.Currency}";
        var hashBytes = SHA256.HashData(Encoding.UTF8.GetBytes(idSource));

        // Convert to hex string and take first 32 characters (OFX FITID max length is typically 255, but shorter is better)
        return Convert.ToHexString(hashBytes)[..32];
    }
}
