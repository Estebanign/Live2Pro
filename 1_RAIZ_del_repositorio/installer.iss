; Inno Setup 6 - instalador de Live2Pro (requiere administrador: registra la cámara virtual)
[Setup]
AppName=Live2Pro
AppVersion=0.2
DefaultDirName={autopf}\Live2Pro
DefaultGroupName=Live2Pro
OutputBaseFilename=Live2Pro-Setup
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
PrivilegesRequired=admin

[Files]
Source: "dist\Live2Pro\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Live2Pro"; Filename: "{app}\Live2Pro.exe"
Name: "{autodesktop}\Live2Pro"; Filename: "{app}\Live2Pro.exe"

[Run]
Filename: "{sys}\regsvr32.exe"; Parameters: "/s ""{app}\driver\UnityCaptureFilter64.dll"""; Flags: runhidden skipifdoesntexist; StatusMsg: "Registrando cámara virtual..."
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/s ""{app}\driver\UnityCaptureFilter32.dll"""; Flags: runhidden skipifdoesntexist

[UninstallRun]
Filename: "{sys}\regsvr32.exe"; Parameters: "/u /s ""{app}\driver\UnityCaptureFilter64.dll"""; Flags: runhidden
Filename: "{syswow64}\regsvr32.exe"; Parameters: "/u /s ""{app}\driver\UnityCaptureFilter32.dll"""; Flags: runhidden skipifdoesntexist
