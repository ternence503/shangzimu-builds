@echo off
rem Keep spaced Visual Studio paths inside cmd, not nested PowerShell /c quotes.
call "%~1" -arch=x64 -host_arch=x64 >nul
if errorlevel 1 exit /b 1
set PATH
set LIB
set INCLUDE
set VCToolsInstallDir
set WindowsSdkDir
set WindowsSDKVersion
exit /b 0
