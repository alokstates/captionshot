; Inno Setup script for CaptionShot (Inno Setup 7; also compiles with 6.x).
; Per-user install: no admin rights, no UAC prompt. Built by build.bat.

#define AppName "CaptionShot"
#define AppVersion "1.1.1"
#define AppExe "CaptionShot.exe"

[Setup]
; Never change AppId: Windows uses it to recognise upgrades of the same app.
AppId={{6E4C2B1A-9F3D-4C7E-A2B8-5D1F0E7C3A94}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=alokstates
AppCopyright=Copyright (c) 2026 alokstates
AppPublisherURL=https://github.com/alokstates/captionshot
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=CaptionShot-Setup-{#AppVersion}
SetupIconFile=captionshot.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; The app holds this mutex while running: setup and uninstall ask to close it first.
AppMutex=Local\CaptionShot_single_instance,CaptionShot_single_instance
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "startup"; Description: "Start {#AppName} when I sign in to Windows"; GroupDescription: "Options:"
Name: "prtsc"; Description: "Use the Print Screen key for {#AppName} (turns off Snipping Tool's use of it)"; GroupDescription: "Options:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "..\dist\CaptionShot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same value name the app's own "Start with Windows" switch uses, so both stay in sync.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: startup
Root: HKCU; Subkey: "Control Panel\Keyboard"; ValueType: dword; ValueName: "PrintScreenKeyForSnippingEnabled"; ValueData: 0; Tasks: prtsc

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

; Uninstall keeps %APPDATA%\CaptionShot (settings, learned Hindi words) so a reinstall keeps them,
; and leaves the Print Screen setting as the user chose it.
