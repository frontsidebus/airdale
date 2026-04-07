@echo off
:: =============================================================================
:: MERLIN Overlay — Compact always-on-top window for use over MSFS
:: Uses PowerShell to set the window as always-on-top after launch.
:: =============================================================================

set MERLIN_URL=http://localhost:3838/overlay

:: Find browser
set BROWSER=
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set BROWSER=C:\Program Files\Google\Chrome\Application\chrome.exe
if "%BROWSER%"=="" if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set BROWSER=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if "%BROWSER%"=="" if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" set BROWSER=C:\Program Files\Microsoft\Edge\Application\msedge.exe

if "%BROWSER%"=="" (
    echo No supported browser found. Opening in default browser...
    start %MERLIN_URL%
    exit /b
)

:: Launch browser in app mode
start "" "%BROWSER%" --app=%MERLIN_URL% --window-size=420,600 --window-position=1480,50 --new-window

:: Wait for window to open, then set always-on-top via PowerShell
timeout /t 3 /nobreak >nul

powershell -Command ^
  "Add-Type @'`n"^
  "using System;`n"^
  "using System.Runtime.InteropServices;`n"^
  "public class WinAPI {`n"^
  "  [DllImport(\"user32.dll\")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);`n"^
  "  [DllImport(\"user32.dll\")] public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);`n"^
  "}`n"^
  "'@;`n"^
  "$HWND_TOPMOST = [IntPtr]::new(-1);`n"^
  "$SWP_NOMOVE = 0x0002; $SWP_NOSIZE = 0x0001;`n"^
  "$w = [WinAPI]::FindWindow($null, 'MERLIN // OVERLAY');`n"^
  "if ($w -ne [IntPtr]::Zero) { [WinAPI]::SetWindowPos($w, $HWND_TOPMOST, 0, 0, 0, 0, $SWP_NOMOVE -bor $SWP_NOSIZE); Write-Host 'MERLIN overlay set to always-on-top' } else { Write-Host 'Window not found - try again in a few seconds' }"
