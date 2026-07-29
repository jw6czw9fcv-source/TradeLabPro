; Inno Setup script — builds TradeLabPro-Setup-<version>.exe, a normal Windows
; installer with a Start Menu entry, an optional desktop shortcut, and an entry
; in Settings > Apps so it uninstalls like anything else.
;
; Build (after pyinstaller has produced dist\TradeLabPro.exe):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\TradeLabPro.iss
; or just run: python tools\build_release.py
;
; Installs per-user into %LOCALAPPDATA%\Programs, the same place VS Code and
; Teams go. That means no admin prompt on install or uninstall; a Program Files
; install would need one every time and buys nothing for a single-user desktop
; app.
;
; Your data is NOT touched by install or uninstall. It lives in
; %LOCALAPPDATA%\TradeLab Pro (see config.user_data_dir), deliberately outside
; the install directory, so upgrading or removing the app never touches your
; portfolio, journal or alerts.

#define AppName "TradeLab Pro"
#define AppExe "TradeLabPro.exe"
#define AppPublisher "Pierre Budai"
; Read the version straight out of VERSION so the installer can never claim a
; different version from the app it contains.
#define AppVersion Trim(FileRead(FileOpen("..\VERSION")))

[Setup]
AppId={{8F3A6E21-4B7C-4E59-9C1D-TRADELABPRO01}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=Output
OutputBaseFilename=TradeLabPro-Setup-{#AppVersion}
SetupIconFile=..\resources\tradelab.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user install: no UAC prompt, and it still appears in Settings > Apps.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
; The app is one big self-contained executable, so there is nothing to read.
LicenseFile=
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenuicon"; Description: "Add a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\resources\tradelab.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\tradelab.ico"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\tradelab.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Windows 10/11 blocks programmatic taskbar pinning outright - Microsoft
// removed the API precisely so installers could not do it. Rather than pretend
// otherwise (or ship one of the undocumented hacks that break on every
// update), the last page says plainly what the single manual step is.
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    WizardForm.FinishedLabel.Caption :=
      WizardForm.FinishedLabel.Caption + #13#10#13#10 +
      'To pin TradeLab Pro to your taskbar: open it, then right-click its ' +
      'taskbar button and choose "Pin to taskbar". Windows does not allow ' +
      'installers to do this for you.';
end;
