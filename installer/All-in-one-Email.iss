; Inno Setup script for All-in-one-Email.
;
; Build the app first, then this:
;   .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean All-in-one-Email.spec
;   "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer\All-in-one-Email.iss
;
; Produces installer\Output\All-in-one-Email-Setup-<version>.exe.

#define AppName "All-in-one-Email"
#define AppVersion "0.1.0"
#define AppPublisher "All-in-one-Email"
#define AppExe "All-in-one-Email.exe"

[Setup]
; AppId identifies the application across versions. Keep it fixed forever:
; change it and Windows stops recognising a new build as an upgrade of the old
; one, leaving the user with two installations side by side.
AppId={{1159E9F7-4FF1-4ADC-ACEE-D03656207A92}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}

; "lowest" installs under the user's own profile and never raises a UAC prompt.
; With it, {autopf} resolves to %LOCALAPPDATA%\Programs — no administrator, no
; shared machine state, and the uninstall entry belongs to this user.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; The app is 64-bit Python and 64-bit Qt; there is nothing to run on x86.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=Output
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\assets\icons\app.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern

; The payload is mostly Qt libraries and Chromium resources, which compress
; well; solid LZMA2 roughly halves what the user downloads. It costs build time
; and memory here, not on their machine.
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; recursesubdirs picks up _internal in full. The exe must be listed separately
; only because it is the one file the shortcuts point at.
Source: "..\dist\{#AppName}\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "{#AppExe}"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only what the application generates inside its own program directory. The
; account store, message history and settings live in %APPDATA%\EmailAggregator
; and are deliberately left alone: uninstalling must not silently destroy the
; user's mail history, and a reinstall should find everything where it was.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
