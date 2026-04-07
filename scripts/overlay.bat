@echo off
:: =============================================================================
:: MERLIN Overlay — Always-on-top launcher
:: Delegates to overlay.ps1 which handles browser launch + Win32 pinning.
:: =============================================================================
powershell -ExecutionPolicy Bypass -File "%~dp0overlay.ps1"
