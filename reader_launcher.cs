using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Windows.Forms;

internal static class ReaderLauncher
{
    // Leave the original quoting of PDF paths and the caller's working directory intact.
    private static string DocumentArguments()
    {
        string line = Environment.CommandLine.TrimStart();
        bool inQuotes = false;
        for (int i = 0; i < line.Length; i++)
        {
            if (line[i] == '"') inQuotes = !inQuotes;
            else if (!inQuotes && (line[i] == ' ' || line[i] == '\t'))
                return line.Substring(i + 1);
        }
        return String.Empty;
    }

    private static Version ReadVersion(string folder)
    {
        Version version;
        string name = Path.GetFileName(folder);
        return Version.TryParse(name, out version) && version.Build >= 0 &&
               version.Revision == -1 && version.ToString() == name ? version : null;
    }

    [STAThread]
    private static int Main()
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
                    var info = new ProcessStartInfo(reader.File, DocumentArguments());
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
