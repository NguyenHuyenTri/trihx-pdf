using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;

internal static class ReaderLauncher
{
    // ProcessStartInfo on .NET Framework accepts a single Windows command line.
    private static string QuoteArgument(string argument)
    {
        var quoted = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char ch in argument)
        {
            if (ch == '\\')
            {
                backslashes++;
                continue;
            }
            quoted.Append('\\', ch == '"' ? 2 * backslashes + 1 : backslashes);
            quoted.Append(ch);
            backslashes = 0;
        }
        return quoted.Append('\\', 2 * backslashes).Append('"').ToString();
    }

    private static Version ReadVersion(string folder)
    {
        Version version;
        string name = Path.GetFileName(folder);
        return Version.TryParse(name, out version) && version.Build >= 0 &&
               version.Revision == -1 && version.ToString() == name ? version : null;
    }

    [STAThread]
    private static int Main(string[] args)
    {
        string root = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "trihx-versions");
        string error = "Chưa tìm thấy bản TRIHX PDF đã cài.";
        try
        {
            var readers = Directory.EnumerateDirectories(root)
                .Select(folder => new { Version = ReadVersion(folder), File = Path.Combine(folder, "HX PDF.exe") })
                .Where(reader => reader.Version != null && File.Exists(reader.File))
                .OrderByDescending(reader => reader.Version);
            foreach (var reader in readers)
            {
                try
                {
                    var info = new ProcessStartInfo(reader.File, String.Join(" ", args.Select(QuoteArgument)));
                    info.UseShellExecute = false;
                    Process.Start(info);
                    return 0;
                }
                catch (Win32Exception ex) { error = ex.Message; }
            }
        }
        catch (IOException ex) { error = ex.Message; }
        catch (UnauthorizedAccessException ex) { error = ex.Message; }
        MessageBox.Show(error, "TRIHX PDF", MessageBoxButtons.OK, MessageBoxIcon.Error);
        return 1;
    }
}
