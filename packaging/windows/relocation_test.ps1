# Native Windows acceptance helper. It does not install or change the machine-wide network.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BundleDir,
    [Parameter(Mandatory=$true)][string]$SpeechFile,
    [Parameter(Mandatory=$true)][string]$ReportFile
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows native execution is required.' }
$BundleDir = [IO.Path]::GetFullPath($BundleDir)
$SpeechFile = [IO.Path]::GetFullPath($SpeechFile)
$ReportFile = [IO.Path]::GetFullPath($ReportFile)
if (Test-Path -LiteralPath $ReportFile) { throw 'ReportFile already exists; no report will be overwritten.' }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $ReportFile) -PathType Container)) { throw 'ReportFile parent directory must already exist.' }

$TaskId = [Guid]::NewGuid().ToString('N')
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ('上字幕 移動驗證 ' + $TaskId)
$MovedBundle = Join-Path $TempRoot '已移動的應用程式 含空白'
$FrozenReport = Join-Path $TempRoot 'frozen-self-test.json'
$EnvironmentNames = @('PATH', 'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX',
    'CONDA_DEFAULT_ENV', 'LOCALAPPDATA', 'APPDATA', 'WHISPER_PREVIEW_DATA_DIR',
    'WHISPER_APP_DATA_DIR', 'SHANGZIMU_TEST_AUDIO', 'HF_HOME', 'HF_HUB_OFFLINE',
    'HF_HUB_DISABLE_TELEMETRY', 'TRANSFORMERS_OFFLINE')
$SavedEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
}
$RuleNames = New-Object 'System.Collections.Generic.List[string]'
$Evidence = [ordered]@{
    status = 'failed'; task = 'windows-frozen-relocation';
    relocated_bundle = $MovedBundle; source_bundle = $BundleDir;
    restricted_path = $true; isolated_appdata = $true;
    firewall_rules = @(); firewall_application = 'not_applied';
    network_denial_proven = $false;
    network_denial_note = 'No independent outbound-denial probe was performed. Applying block rules alone does not prove OS network denial.';
    speech_transcribed_and_srt_exported = $false
}
try {
    if (-not (Test-Path -LiteralPath (Join-Path $BundleDir '上字幕.exe') -PathType Leaf)) { throw 'BundleDir must contain the complete frozen onedir application.' }
    if (-not (Test-Path -LiteralPath $SpeechFile -PathType Leaf)) { throw 'SpeechFile must be a real audio fixture.' }
    New-Item -ItemType Directory -Path $TempRoot | Out-Null
    New-Item -ItemType Directory -Path $MovedBundle | Out-Null
    Get-ChildItem -LiteralPath $BundleDir -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $MovedBundle -Recurse
    }
    $MovedSpeech = Join-Path $TempRoot ('實際語音 測試' + [IO.Path]::GetExtension($SpeechFile))
    Copy-Item -LiteralPath $SpeechFile -Destination $MovedSpeech
    foreach ($Directory in @('user-local', 'user-roaming', 'progress', 'hf-cache')) {
        New-Item -ItemType Directory -Path (Join-Path $TempRoot $Directory) | Out-Null
    }
    foreach ($Name in @('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV')) {
        [Environment]::SetEnvironmentVariable($Name, $null, 'Process')
    }
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:LOCALAPPDATA = Join-Path $TempRoot 'user-local'
    $env:APPDATA = Join-Path $TempRoot 'user-roaming'
    $env:WHISPER_PREVIEW_DATA_DIR = Join-Path $TempRoot 'progress'
    $env:WHISPER_APP_DATA_DIR = $env:WHISPER_PREVIEW_DATA_DIR
    $env:HF_HOME = Join-Path $TempRoot 'hf-cache'
    $env:SHANGZIMU_TEST_AUDIO = $MovedSpeech
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    $env:HF_HUB_DISABLE_TELEMETRY = '1'

    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    $IsAdmin = $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($IsAdmin -and (Get-Command New-NetFirewallRule -ErrorAction SilentlyContinue)) {
        $Programs = @(Join-Path $MovedBundle '上字幕.exe')
        $Programs += @(Get-ChildItem -LiteralPath $MovedBundle -File -Recurse | Where-Object {
            $_.Name -in @('ffmpeg.exe', 'ffprobe.exe')
        } | ForEach-Object { $_.FullName })
        $Index = 0
        foreach ($Program in ($Programs | Select-Object -Unique)) {
            $RuleName = "ShangZiMu-Relocation-$TaskId-$Index"
            New-NetFirewallRule -Name $RuleName -DisplayName $RuleName -Direction Outbound `
                -Action Block -Program $Program -Profile Any -Enabled True | Out-Null
            $RuleNames.Add($RuleName)
            $Evidence.firewall_application = 'applied_not_proven'
            $Evidence.firewall_rules = @($RuleNames.ToArray())
            $Index++
        }
        $Evidence.firewall_application = 'applied_not_proven'
        $Evidence.firewall_rules = @($RuleNames.ToArray())
    } else {
        $Evidence.firewall_application = 'unavailable_or_not_elevated'
    }

    $Exe = Join-Path $MovedBundle '上字幕.exe'
    $Process = Start-Process -FilePath $Exe -WorkingDirectory $MovedBundle `
        -ArgumentList @('--self-test', ('"' + $FrozenReport + '"')) -PassThru -Wait
    $Evidence.exit_code = $Process.ExitCode
    if ($Process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $FrozenReport)) {
        throw 'Relocated frozen app failed or did not write its self-test report.'
    }
    $Result = Get-Content -LiteralPath $FrozenReport -Raw | ConvertFrom-Json
    $Evidence.frozen_result = $Result
    if ($Result.status -ne 'passed' -or $Result.speech_transcribed_and_srt_exported -ne $true) {
        throw 'The actual relocated app did not pass speech transcription and SRT export.'
    }
    $Evidence.speech_transcribed_and_srt_exported = $true
    $Evidence.status = 'passed'
} catch {
    $Evidence.error = $_.Exception.Message
    if (Test-Path -LiteralPath $FrozenReport) {
        $Evidence.frozen_report_raw = Get-Content -LiteralPath $FrozenReport -Raw
    }
} finally {
    $CleanupErrors = @()
    foreach ($RuleName in $RuleNames) {
        try { Remove-NetFirewallRule -Name $RuleName -ErrorAction Stop }
        catch { $CleanupErrors += "Rule $RuleName cleanup failed: $($_.Exception.Message)" }
    }
    foreach ($Name in $EnvironmentNames) {
        [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], 'Process')
    }
    $Evidence.firewall_cleanup_errors = $CleanupErrors
    if ($CleanupErrors.Count -gt 0) { $Evidence.status = 'failed' }
    $Evidence.retained_evidence_directory = $TempRoot
    # Exclusive creation prevents even concurrent tests from overwriting a report.
    $Json = $Evidence | ConvertTo-Json -Depth 20
    $Stream = [IO.File]::Open($ReportFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $Bytes = [Text.UTF8Encoding]::new($true).GetBytes($Json)
        $Stream.Write($Bytes, 0, $Bytes.Length)
    } finally { $Stream.Dispose() }
}
if ($Evidence.status -ne 'passed') { throw "Relocation acceptance failed. Evidence retained at $ReportFile" }
Write-Host "Relocation acceptance passed: $ReportFile. OS outbound denial remains unproven."
