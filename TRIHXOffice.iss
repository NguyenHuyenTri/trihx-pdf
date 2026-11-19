#define AppVersion ReadIni(AddBackslash(SourcePath) + "version.ini", "app", "version")
#if AppVersion == ""
  #error Application version missing from version.ini
#endif

[Setup]
AppId=TRIHX.Office.Windows
AppName=TRIHX PDF
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\TRIHX Office
DefaultGroupName=TRIHX PDF
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
MinVersion=10.0
OutputDir=dist
OutputBaseFilename=TRIHX Office Setup
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\HX PDF.exe
Compression=lzma2
SolidCompression=yes
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Files]
Source: "build\launcher\HX PDF.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\HX PDF.exe"; DestDir: "{app}\trihx-versions\{#AppVersion}"; Flags: ignoreversion

[UninstallDelete]
Type: filesandordirs; Name: "{app}\trihx-versions"

[Icons]
Name: "{group}\TRIHX PDF"; Filename: "{app}\HX PDF.exe"
Name: "{userdesktop}\TRIHX PDF"; Filename: "{app}\HX PDF.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\HXPDF.Document"; ValueType: string; ValueData: "TRIHX PDF"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\HXPDF.Document\DefaultIcon"; ValueType: string; ValueData: "{app}\HX PDF.exe,0"
Root: HKCU; Subkey: "Software\Classes\HXPDF.Document\shell\open\command"; ValueType: string; ValueData: """{app}\HX PDF.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "HXPDF.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\HX PDF.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "TRIHX PDF"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\HX PDF.exe\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\HX PDF.exe\shell\open\command"; ValueType: string; ValueData: """{app}\HX PDF.exe"" ""%1"""

[Run]
Filename: "{app}\HX PDF.exe"; Description: "Open TRIHX PDF"; Flags: nowait postinstall skipifsilent
