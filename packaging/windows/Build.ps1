# Windows native developer build only. End users never run this script.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$PreparedResources,
    [Parameter(Mandatory=$true)][string]$InnoCompiler,
    [string]$Version = '1.4.0',
    [string]$BuildRoot = (Join-Path $PSScriptRoot 'build-local')
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Must build on Windows x64; Mac cross-build is not supported.' }
if ($Version -notmatch '^\d+\.\d+\.\d+(?:\.\d+)?$') { throw 'Version must be numeric.' }
foreach ($inputPath in @($PythonExe, $PreparedResources, $InnoCompiler)) {
    if (-not (Test-Path -LiteralPath $inputPath)) { throw "Input does not exist: $inputPath" }
}
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Exe" }
}
Invoke-Checked -Exe $PythonExe -Arguments @('-c', 'import sys,platform; assert sys.version_info[:2]==(3,12); assert platform.machine().lower() in ("amd64","x86_64"); import tkinter; tkinter.Tcl()')
$BuildRoot = [IO.Path]::GetFullPath($BuildRoot)
if (Test-Path -LiteralPath $BuildRoot) { throw 'BuildRoot already exists. Use a new empty build location; no files will be removed.' }
New-Item -ItemType Directory -Path $BuildRoot | Out-Null
$Venv = Join-Path $BuildRoot 'venv'
Invoke-Checked -Exe $PythonExe -Arguments @('-m', 'venv', $Venv)
$BuildPython = Join-Path $Venv 'Scripts\python.exe'
Invoke-Checked -Exe $BuildPython -Arguments @('-m','pip','install','--only-binary=:all:','-r',(Join-Path $PSScriptRoot 'requirements-build.txt'))
Invoke-Checked -Exe $BuildPython -Arguments @('-m','pip','check')
& $BuildPython -m pip freeze | Set-Content -LiteralPath (Join-Path $BuildRoot 'dependency-lock.txt') -Encoding UTF8
if ($LASTEXITCODE -ne 0) { throw 'Dependency lock could not be recorded.' }
# The supplied resources must include real CT2 model files and redistribution notices.
# No model or binary is downloaded by the finished app.
Invoke-Checked -Exe $BuildPython -Arguments @((Join-Path $PSScriptRoot 'check_inputs.py'), [IO.Path]::GetFullPath($PreparedResources))
$LanguageFile = Join-Path $PreparedResources 'licenses\inno-setup\ChineseTraditional.isl'
if (-not (Test-Path -LiteralPath $LanguageFile -PathType Leaf)) { throw 'Prepared resources lack the pinned Traditional Chinese installer language.' }
$OldResourceEnv = $env:SHANGZIMU_BUILD_RESOURCES
$OldDataEnv = $env:WHISPER_PREVIEW_DATA_DIR
try {
    $env:SHANGZIMU_BUILD_RESOURCES = [IO.Path]::GetFullPath($PreparedResources)
    $DistDir = Join-Path $BuildRoot 'dist'
    Invoke-Checked -Exe $BuildPython -Arguments @('-m','PyInstaller','--noconfirm','--distpath',$DistDir,'--workpath',(Join-Path $BuildRoot 'pyinstaller'),(Join-Path $PSScriptRoot 'up-subtitles.spec'))
    $Bundle = Join-Path $DistDir '上字幕'
    $Exe = Join-Path $Bundle '上字幕.exe'
    $Report = Join-Path $BuildRoot 'frozen-self-test.json'
    $env:WHISPER_PREVIEW_DATA_DIR = Join-Path $BuildRoot 'isolated-user-data'
    # Windowed PE applications need Start-Process -Wait, not a shell invocation.
    $Process = Start-Process -FilePath $Exe -ArgumentList @('--self-test', ('"' + $Report + '"')) -Wait -PassThru
    if ($Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Report)) { throw 'Frozen app self-test failed or did not generate a report.' }
    $Result = Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json
    if ($Result.status -ne 'passed') { throw 'Frozen self-test report does not declare passed.' }
    $Release = Join-Path $BuildRoot 'release'
    New-Item -ItemType Directory -Path $Release | Out-Null
    Invoke-Checked -Exe $InnoCompiler -Arguments @("/DBundleDir=$Bundle", "/DReleaseDir=$Release", "/DAppVersion=$Version", "/DLanguageFile=$LanguageFile", (Join-Path $PSScriptRoot 'installer.iss'))
    Write-Host "Built installer under $Release. This is not a clean-machine acceptance result."
} finally {
    $env:SHANGZIMU_BUILD_RESOURCES = $OldResourceEnv
    $env:WHISPER_PREVIEW_DATA_DIR = $OldDataEnv
}
