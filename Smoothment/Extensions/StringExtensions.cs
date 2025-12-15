using System.Text.RegularExpressions;

namespace Smoothment.Extensions;

public static partial class StringExtensions
{
    [GeneratedRegex(@"\s+")]
    private static partial Regex WhitespaceRegex();

    public static string RemoveLastWord(this string str)
    {
        var lastSpaceIndex = str.LastIndexOf(' ');
        return lastSpaceIndex == -1 ? string.Empty : str[..lastSpaceIndex];
    }

    public static string NormalizeWhitespace(this string? input)
    {
        if (string.IsNullOrWhiteSpace(input))
            return string.Empty;

        return WhitespaceRegex().Replace(input, " ").Trim();
    }
}
