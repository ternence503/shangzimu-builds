param([string]$Model = "small", [switch]$OnlyLaunch)
$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDataDir = Join-Path $env:LOCALAPPDATA "WhisperGui-SubtitlePreview"
$VenvDir = Join-Path $AppDataDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ModelsDir = Join-Path $AppDataDir "models"
$FfmpegDir = Join-Path $AppDataDir "ffmpeg"
$CurrentVersion = (Get-Content (Join-Path $ScriptRoot "version.txt") -Raw).Trim()
$InstalledVersionFile = Join-Path $VenvDir ".installed_version"
$LogDir = Join-Path $AppDataDir "logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogFile = Join-Path $LogDir "last-launch.log"
Start-Transcript -Path $LogFile -Force | Out-Null
$env:WHISPER_PREVIEW = "1"
$env:WHISPER_LOCAL_ONLY = "1"
$env:WHISPER_MODEL_DIR = Join-Path $ModelsDir "original"
$env:WHISPER_FASTER_MODEL_DIR = Join-Path $ModelsDir "faster-small"
$env:WHISPER_APP_DATA_DIR = $AppDataDir
$env:HF_HUB_DISABLE_TELEMETRY = "1"

function Invoke-Python([string]$Exe, [string[]]$Arguments) {
    # Windows PowerShell 5 may promote native stderr to NativeCommandError.
    # Keep stderr visible but use the native exit code as the success criterion.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Exe @Arguments
        $nativeExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($nativeExit -ne 0) { throw "程式準備失敗（代碼 $nativeExit）。請查看上方詳細原因。" }
}

function Test-PythonImports([string]$Exe, [string]$Imports) {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Exe -c $Imports *> $null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
    finally { $ErrorActionPreference = $previousPreference }
}

function Test-VideoTool([string]$Exe) {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Exe -version *> $null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
    finally { $ErrorActionPreference = $previousPreference }
}

function Resolve-Python {
    # Only Python 3.12 is supported by this installer; do not select arbitrary newer runtimes.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            $result = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $result) { return ($result | Select-Object -Last 1).Trim() }
        } catch { }
        finally { $ErrorActionPreference = $previousPreference }
    }
    $localPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $localPython) { return $localPython }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "此電腦沒有 Python 3.12，且無法自動安裝。請從 python.org 安裝 Python 3.12（包含 Tcl/Tk），再雙擊啟動檔。公司若禁止安裝，請洽資訊人員。"
    }
    Write-Host "[1/3] 安裝 Python 3.12（僅目前使用者）。"
    & winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python 安裝未完成。請確認公司權限與網路，再重試啟動檔。" }
    if (Test-Path $localPython) { return $localPython }
    throw "Python 安裝後尚未找到。請關閉本視窗，再雙擊啟動檔重試。"
}

function Ensure-Packages {
    if (Test-Path $VenvPython) {
        if (-not (Test-PythonImports -Exe $VenvPython -Imports "import tkinter")) {
            Move-Item -LiteralPath $VenvDir -Destination (Join-Path $AppDataDir ("venv-backup-" + [guid]::NewGuid().ToString("N")))
        }
    }
    if (-not (Test-Path $VenvPython)) {
        $basePython = Resolve-Python
        Invoke-Python -Exe $basePython -Arguments @("-m", "venv", $VenvDir)
    }
    $installed = if (Test-Path $InstalledVersionFile) { (Get-Content $InstalledVersionFile -Raw).Trim() } else { "" }
    if (-not (Test-PythonImports -Exe $VenvPython -Imports "import faster_whisper, tkinter, opencc, pip_system_certs") -or $installed -ne $CurrentVersion) {
        Write-Host "[2/3] 準備轉錄程式。下載較大，請保持網路連線。"
        Invoke-Python -Exe $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel")
        Invoke-Python -Exe $VenvPython -Arguments @("-m", "pip", "install", "--only-binary=:all:", "-r", (Join-Path $ScriptRoot "requirements-win.txt"))
        Invoke-Python -Exe $VenvPython -Arguments @("-c", "import faster_whisper, tkinter, opencc, pip_system_certs")
    }
}

function Ensure-Ffmpeg {
    $ffmpeg = Join-Path $FfmpegDir "ffmpeg.exe"
    $ffprobe = Join-Path $FfmpegDir "ffprobe.exe"
    if ((Test-Path $ffmpeg) -and (Test-Path $ffprobe)) {
        if ((Test-VideoTool -Exe $ffmpeg) -and (Test-VideoTool -Exe $ffprobe)) { return }
    }
    # Each attempt has its own explicit staging folder; never delete formal tools or shortcuts.
    $staging = Join-Path $AppDataDir ("ffmpeg-download-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $staging | Out-Null
    $zipPath = Join-Path $staging "ffmpeg.zip"
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Write-Host "準備影片讀取工具（第 $attempt/3 次）。"
            Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zipPath -UseBasicParsing
            Expand-Archive -Path $zipPath -DestinationPath (Join-Path $staging "unpacked") -Force
            $a = Get-ChildItem (Join-Path $staging "unpacked") -Filter ffmpeg.exe -Recurse | Select-Object -First 1
            $b = Get-ChildItem (Join-Path $staging "unpacked") -Filter ffprobe.exe -Recurse | Select-Object -First 1
            if (-not $a -or -not $b) { throw "下載檔案缺少影片工具。" }
            if (-not (Test-VideoTool -Exe $a.FullName)) { throw "影片工具不完整。" }
            if (-not (Test-VideoTool -Exe $b.FullName)) { throw "影片資訊工具不完整。" }
            New-Item -ItemType Directory -Path $FfmpegDir -Force | Out-Null
            Copy-Item $a.FullName $ffmpeg -Force
            Copy-Item $b.FullName $ffprobe -Force
            return
        } catch {
            if ($attempt -eq 3) { throw "影片工具下載失敗。請確認網路與磁碟空間後重試。" }
            Start-Sleep -Seconds 2
        }
    }
}

function Create-PreviewShortcut {
    try {
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut((Join-Path $shell.SpecialFolders("Desktop") "Whisper 字幕試用版.lnk"))
        $shortcut.TargetPath = Join-Path $env:SystemRoot "System32\cmd.exe"
        $launcher = Join-Path (Split-Path $ScriptRoot -Parent) "▶ 啟動 Whisper.bat"
        $shortcut.Arguments = "/c `"`"$launcher`"`""
        $shortcut.WorkingDirectory = Split-Path $ScriptRoot -Parent
        $shortcut.WindowStyle = 1
        $shortcut.Description = "Whisper 字幕排版試用版（不影響正式版）"
        $shortcut.Save()
    } catch { Write-Host "無法建立桌面捷徑；仍可從解壓資料夾的啟動檔使用。" }
}

try {
    Write-Host "字幕排版試用版：首次準備需要網路；不會上傳您的音訊或字幕。"
    Write-Host "請保留解壓後的整個資料夾。安裝位置與正式版分開。"
    Write-Host "紀錄位置：$LogFile"
    # Always validate and repair prerequisites, even when an older shortcut supplies OnlyLaunch.
    Ensure-Packages
    Ensure-Ffmpeg
    Write-Host "[3/3] 驗證並準備本機通用語音模型。"
    Invoke-Python -Exe $VenvPython -Arguments @((Join-Path $ScriptRoot "download_model.py"), "small", "--output", $ModelsDir)
    Set-Content $InstalledVersionFile $CurrentVersion
    Create-PreviewShortcut
    $env:PATH = "$FfmpegDir;$env:PATH"
    $env:HF_HUB_OFFLINE = "1"
    Write-Host "準備完成，開啟字幕工具。"
    Invoke-Python -Exe $VenvPython -Arguments @((Join-Path $ScriptRoot "whisper_gui_win.py"))
} catch {
    Write-Host "尚未完成：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "請確認網路、磁碟空間與安裝權限，再雙擊啟動檔重試。紀錄：$LogFile"
    Stop-Transcript | Out-Null
    exit 1
}
Stop-Transcript | Out-Null
exit 0
