using System.Text;

namespace Smoothment.Extensions;

public static class StreamExtensions
{
    public static async Task<Encoding> DetectEncodingAsync(this Stream stream, CancellationToken cancellationToken)
    {
        // BOM check
        var preamble = Encoding.UTF8.GetPreamble();
        var bom = new byte[preamble.Length];
        var x = await stream.ReadAsync(bom, 0, bom.Length, cancellationToken);
        stream.Position = 0;

        if (bom.SequenceEqual(preamble)) return Encoding.UTF8;

        // Check for UTF-8 without BOM
        try
        {
            using var reader = new StreamReader(stream, Encoding.UTF8, false,
                leaveOpen: true);
            var text = await reader.ReadToEndAsync(cancellationToken);
            if (LooksLikeUtf8(text))
            {
                stream.Position = 0;
                return Encoding.UTF8;
            }
        }
        catch
        {
            // ignored
        }

        stream.Position = 0;
        // Using Windows-1251 as a fallback
        try
        {
            var win1251 = Encoding.GetEncoding("windows-1251");
            using var reader = new StreamReader(stream, win1251, false, leaveOpen: true);
            _ = await reader.ReadToEndAsync(cancellationToken);
            stream.Position = 0;
            return win1251;
        }
        catch
        {
            stream.Position = 0;
            return Encoding.Default;
        }
    }

    private static bool LooksLikeUtf8(string text)
    {
        var badCharCount = text.Count(c => c is '?' or '�' or '�');
        var ratio = (double)badCharCount / text.Length;

        return ratio < 0.01;
    }
}
