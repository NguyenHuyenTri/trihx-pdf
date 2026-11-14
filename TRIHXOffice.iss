#define AppVersion "0.1.0"

[Setup]
AppId=TRIHX.Office.Windows
AppName=TRIHX Office
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\TRIHX Office
DefaultGroupName=TRIHX Office
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
Source: "dist\HX PDF.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\TRIHX Office"; Filename: "{app}\HX PDF.exe"
Name: "{userdesktop}\TRIHX Office"; Filename: "{app}\HX PDF.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\HXPDF.Document"; ValueType: string; ValueData: "TRIHX Office PDF"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\HXPDF.Document\DefaultIcon"; ValueType: string; ValueData: "{app}\HX PDF.exe,0"
Root: HKCU; Subkey: "Software\Classes\HXPDF.Document\shell\open\command"; ValueType: string; ValueData: """{app}\HX PDF.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "HXPDF.Document"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\Applications\HX PDF.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "TRIHX Office"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\HX PDF.exe\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\HX PDF.exe\shell\open\command"; ValueType: string; ValueData: """{app}\HX PDF.exe"" ""%1"""

[Run]
Filename: "{app}\HX PDF.exe"; Description: "Open TRIHX Office"; Flags: nowait postinstall skipifsilent
