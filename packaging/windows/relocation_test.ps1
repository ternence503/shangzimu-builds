# Native Windows acceptance helper. Never changes global outbound policies.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BundleDir,
    [Parameter(Mandatory=$true)][string]$SpeechFile,
    [Parameter(Mandatory=$true)][string]$ReportFile,
    [switch]$EnableFirewallProfilesForDisposableCI
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
$ChangedProfiles = New-Object 'System.Collections.Generic.List[string]'
$ProfileSnapshot = @()
$Evidence = [ordered]@{
    status = 'failed'; task = 'windows-frozen-relocation';
    relocated_bundle = $MovedBundle; source_bundle = $BundleDir;
    restricted_path = $true; isolated_appdata = $true;
    firewall_rules = @(); firewall_application = 'not_applied';
    network_denial_proven = $false;
    network_denial_note = 'Not proven until unpatched baseline connects and the same relocated executable cannot connect with its precise block rule.';
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
        $ProfileSnapshot = @(Get-NetFirewallProfile -ErrorAction Stop | Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction)
        $EffectiveBefore = @(Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction Stop | Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction)
        $Evidence.firewall_profiles_before = $ProfileSnapshot
        $Evidence.firewall_profiles_effective_before = $EffectiveBefore
        $Disabled = @($ProfileSnapshot | Where-Object { [string]$_.Enabled -ne 'True' })
        if ($Disabled.Count -gt 0) {
            if (-not $EnableFirewallProfilesForDisposableCI -or
                $env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
                throw 'Firewall profiles are disabled; no machine settings will be changed without the disposable GitHub-hosted CI switch.'
            }
            if (@(($ProfileSnapshot + $EffectiveBefore) | Where-Object { [string]$_.DefaultOutboundAction -eq 'Block' }).Count -gt 0) {
                throw 'Refusing to enable profiles with global outbound Block policy; runner connectivity must not be disrupted.'
            }
            foreach ($Profile in $Disabled) {
                # Track before the mutation so restoration is attempted even if
                # a command succeeds partially then reports an error.
                $ChangedProfiles.Add([string]$Profile.Name)
                Set-NetFirewallProfile -Name $Profile.Name -Enabled True -ErrorAction Stop
            }
        }
        $ProfilesNow = @(Get-NetFirewallProfile -PolicyStore ActiveStore -ErrorAction Stop)
        if (@($ProfilesNow | Where-Object { [string]$_.Enabled -ne 'True' }).Count -gt 0) {
            throw 'Effective firewall profiles are not all enabled; OS denial cannot be proven.'
        }
        $Evidence.firewall_profiles_during = @($ProfilesNow | Select-Object Name, Enabled, DefaultInboundAction, DefaultOutboundAction)
        $Exe = Join-Path $MovedBundle '上字幕.exe'
        function Invoke-NetworkProbe([string]$Destination) {
            if (Test-Path -LiteralPath $Destination) { throw 'Network probe report already exists.' }
            $ProbeProcess = Start-Process -FilePath $Exe -WorkingDirectory $MovedBundle `
                -ArgumentList @('--network-probe', ('"' + $Destination + '"')) -PassThru -Wait
            if ($ProbeProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Destination)) {
                throw 'Unpatched native network probe failed to produce evidence.'
            }
            $Probe = Get-Content -LiteralPath $Destination -Raw | ConvertFrom-Json
            if ($Probe.python_socket_patch_applied -ne $false) {
                throw 'Network evidence must come from an unpatched socket probe.'
            }
            return $Probe
        }
        $BaselinePath = Join-Path $TempRoot 'network-before-block.json'
        $Baseline = Invoke-NetworkProbe -Destination $BaselinePath
        $Evidence.network_baseline = $Baseline
        if ($Baseline.connected -ne $true) {
            throw 'Baseline did not connect; inability to connect cannot prove firewall denial.'
        }
        $Programs = @(Join-Path $MovedBundle '上字幕.exe')
        $Programs += @(Get-ChildItem -LiteralPath $MovedBundle -File -Recurse | Where-Object {
            $_.Name -in @('ffmpeg.exe', 'ffprobe.exe')
        } | ForEach-Object { $_.FullName })
        $Index = 0
        foreach ($Program in ($Programs | Select-Object -Unique)) {
            $RuleName = "ShangZiMu-Relocation-$TaskId-$Index"
            $RuleNames.Add($RuleName)
            New-NetFirewallRule -Name $RuleName -DisplayName $RuleName -Direction Outbound `
                -Action Block -Program $Program -Profile Any -Enabled True | Out-Null
            $Evidence.firewall_application = 'applied_not_proven'
            $Evidence.firewall_rules = @($RuleNames.ToArray())
            $Index++
        }
        $Evidence.firewall_application = 'applied_not_proven'
        $Evidence.firewall_rules = @($RuleNames.ToArray())
        foreach ($RuleName in $RuleNames) {
            $EffectiveRule = Get-NetFirewallRule -Name $RuleName -PolicyStore ActiveStore -ErrorAction Stop
            if ([string]$EffectiveRule.Enabled -ne 'True' -or [string]$EffectiveRule.Action -ne 'Block' -or
                [string]$EffectiveRule.Direction -ne 'Outbound') {
                throw 'Effective application block rule is not active.'
            }
        }
        $BlockedPath = Join-Path $TempRoot 'network-after-block.json'
        $Blocked = Invoke-NetworkProbe -Destination $BlockedPath
        $Evidence.network_with_block = $Blocked
        if ($Blocked.connected -ne $false) {
            throw 'The actual relocated executable still connected with its OS block rule; network denial is not proven.'
        }
        $Evidence.network_denial_proven = $true
        $Evidence.firewall_application = 'applied_and_probe_verified'
        $Evidence.network_denial_note = 'Same relocated executable connected before exact outbound block, then unpatched socket connection failed while effective profiles and application block rules were enabled. Not a proof covering arbitrary subprocesses.'
    } else {
        $Evidence.firewall_application = 'unavailable_or_not_elevated'
        throw 'Administrator privileges and NetSecurity firewall commands are required for real OS denial evidence.'
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
    foreach ($Name in $ChangedProfiles) {
        try {
            $Original = $ProfileSnapshot | Where-Object { $_.Name -eq $Name }
            Set-NetFirewallProfile -Name $Name -Enabled $Original.Enabled -ErrorAction Stop
            $Restored = Get-NetFirewallProfile -Name $Name -ErrorAction Stop
            if ([string]$Restored.Enabled -ne [string]$Original.Enabled) {
                throw 'Enabled state differs after restoration.'
            }
        } catch { $CleanupErrors += "Profile $Name restoration failed: $($_.Exception.Message)" }
    }
    foreach ($Name in $EnvironmentNames) {
        [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], 'Process')
    }
    $Evidence.firewall_cleanup_errors = $CleanupErrors
    $Evidence.firewall_profiles_temporarily_enabled = @($ChangedProfiles.ToArray())
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
Write-Host "Relocation acceptance passed: $ReportFile. Actual executable OS outbound denial was probe-verified."
