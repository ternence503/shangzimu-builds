#ifndef BundleDir
  #error BundleDir must be supplied by Build.ps1
#endif
#ifndef ReleaseDir
  #error ReleaseDir must be supplied by Build.ps1
#endif
#ifndef AppVersion
  #define AppVersion "1.4.0"
#endif
#ifndef LanguageFile
  #error Pinned Traditional Chinese language file must be supplied by Build.ps1
#endif
[Setup]
AppId={{83A70D11-33C6-4C94-AE6D-0D45EC4D9C33}
AppName=上字幕
AppVersion={#AppVersion}
AppPublisher=Ternence
DefaultDirName={localappdata}\Programs\ShangZiMu
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#ReleaseDir}
OutputBaseFilename=上字幕-Windows-x64-{#AppVersion}-安裝
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\上字幕.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
[Languages]
Name: "traditionalchinese"; MessagesFile: "{#LanguageFile}"
[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourcePath}\installation-owner.txt"; DestDir: "{app}"; DestName: ".shangzimu-installation"; Flags: ignoreversion
[Icons]
Name: "{userprograms}\上字幕"; Filename: "{app}\上字幕.exe"; WorkingDir: "{app}"; Comment: "本機轉錄與字幕整理"
[Run]
Filename: "{app}\上字幕.exe"; Description: "立即開啟上字幕"; Flags: nowait postinstall skipifsilent
[Code]
function InitializeSetup(): Boolean;
var
  InstallDir: String;
begin
  InstallDir := ExpandConstant('{localappdata}\Programs\ShangZiMu');
  Result := True;
  { Never adopt an unrelated directory that happens to have our name. }
  if DirExists(InstallDir) and
    (not FileExists(InstallDir + '\unins000.exe') or
     not FileExists(InstallDir + '\.shangzimu-installation')) then
  begin
    SuppressibleMsgBox('安裝位置已存在，但不是可辨識的上字幕安裝。請先由管理者確認，不會覆寫此資料夾。', mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ActualDir: String;
  ExpectedDir: String;
begin
  Result := '';
  ActualDir := ExpandConstant('{app}');
  ExpectedDir := ExpandConstant('{localappdata}\Programs\ShangZiMu');
  { DisableDirPage does not prevent command-line /DIR overrides. }
  if CompareText(AddBackslash(ActualDir), AddBackslash(ExpectedDir)) <> 0 then
  begin
    Result := '上字幕只能安裝到預設的個人應用程式位置，不會覆寫其他資料夾。';
    Exit;
  end;
  if DirExists(ActualDir) and
    (not FileExists(ActualDir + '\unins000.exe') or
     not FileExists(ActualDir + '\.shangzimu-installation')) then
    Result := '安裝位置已有無法辨識的資料，上字幕不會覆寫它。請由管理者確認。';
end;
