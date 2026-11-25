; Inno Setup 6 - instalador de Live2Pro
[Setup]
AppName=Live2Pro
AppVersion=0.1
DefaultDirName={autopf}\Live2Pro
DefaultGroupName=Live2Pro
OutputBaseFilename=Live2Pro-Setup
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
PrivilegesRequired=lowest

[Files]
Source: "dist\Live2Pro\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Live2Pro"; Filename: "{app}\Live2Pro.exe"
Name: "{autodesktop}\Live2Pro"; Filename: "{app}\Live2Pro.exe"
