; Inno Setup script for EK's Image Wise  (build.py passes the /D values below)
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\EKsImageWise"
#endif
#ifndef OutDir
  #define OutDir "..\dist\installer"
#endif
#define MyAppName "EK's Image Wise"
#define MyAppExe "EKsImageWise.exe"

[Setup]
AppId={{6B0E3F6A-2F0B-4C7B-9A57-3D7B1C4E9A21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=EK
DefaultDirName={autopf}\EK Image Wise
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir={#OutDir}
OutputBaseFilename=EKsImageWise-Setup-{#MyAppVersion}
SetupIconFile=..\imagewise\assets\ekiw.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; lets the user choose "just for me" (no admin rights needed) or "all users"
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent

; Your own plugins, logs and settings live in your home folder (EKImageWise) and are kept on uninstall.
