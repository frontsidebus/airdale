# =============================================================================
# MERLIN Overlay — Always-on-top launcher
# Run from Windows: powershell -ExecutionPolicy Bypass -File scripts\overlay.ps1
# =============================================================================

$MerlinUrl = "http://localhost:3838/overlay"

# Find browser
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$chromeX86 = "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
$edge = "C:\Program Files\Microsoft\Edge\Application\msedge.exe"

$browser = if (Test-Path $chrome) { $chrome }
           elseif (Test-Path $chromeX86) { $chromeX86 }
           elseif (Test-Path $edge) { $edge }
           else { $null }

if (-not $browser) {
    Write-Host "No supported browser found. Opening in default browser..."
    Start-Process $MerlinUrl
    exit
}

# Launch in app mode
Write-Host "Launching MERLIN overlay..."
Start-Process $browser -ArgumentList "--app=$MerlinUrl", "--window-size=420,600", "--new-window"

# Wait for the window to appear
Write-Host "Waiting for overlay window..."
Start-Sleep -Seconds 4

# Win32 API for always-on-top
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Collections.Generic;

public class WinHelper {
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    public static List<IntPtr> FindWindowsByTitle(string search) {
        var results = new List<IntPtr>();
        EnumWindows((hWnd, lParam) => {
            if (!IsWindowVisible(hWnd)) return true;
            var sb = new StringBuilder(256);
            GetWindowText(hWnd, sb, 256);
            var title = sb.ToString();
            if (title.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0) {
                results.Add(hWnd);
            }
            return true;
        }, IntPtr.Zero);
        return results;
    }
}
"@

# Search for any window with "MERLIN" in the title
$windows = [WinHelper]::FindWindowsByTitle("MERLIN")

if ($windows.Count -eq 0) {
    Write-Host "Window not found. Retrying in 3 seconds..."
    Start-Sleep -Seconds 3
    $windows = [WinHelper]::FindWindowsByTitle("MERLIN")
}

$HWND_TOPMOST = [IntPtr]::new(-1)
$SWP_NOMOVE = 0x0002
$SWP_NOSIZE = 0x0001

if ($windows.Count -gt 0) {
    foreach ($hwnd in $windows) {
        $sb = New-Object System.Text.StringBuilder 256
        [WinHelper]::GetWindowText($hwnd, $sb, 256) | Out-Null
        $title = $sb.ToString()

        # Only pin MERLIN overlay windows, not other MERLIN things
        if ($title -match "MERLIN" -and $title -match "OVERLAY|localhost:3838") {
            [WinHelper]::SetWindowPos($hwnd, $HWND_TOPMOST, 0, 0, 0, 0, $SWP_NOMOVE -bor $SWP_NOSIZE) | Out-Null
            Write-Host "MERLIN overlay pinned on top: '$title'"
        }
    }
} else {
    Write-Host "Could not find MERLIN overlay window."
    Write-Host "Open http://localhost:3838/overlay manually and re-run this script."
}
