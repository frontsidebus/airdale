@echo off
:: =============================================================================
:: MERLIN Overlay — Compact always-on-top window for use over MSFS
:: Opens as a borderless app window that floats above the sim.
:: =============================================================================

set MERLIN_URL=http://localhost:3838/overlay

:: Chrome with always-on-top, small window, app mode (no address bar)
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app=%MERLIN_URL% --window-size=420,600 --window-position=1480,50 --always-on-top
    exit /b
)

if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --app=%MERLIN_URL% --window-size=420,600 --window-position=1480,50 --always-on-top
    exit /b
)

:: Edge fallback
if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files\Microsoft\Edge\Application\msedge.exe" --app=%MERLIN_URL% --window-size=420,600 --window-position=1480,50 --always-on-top
    exit /b
)

:: Fallback
start %MERLIN_URL%
