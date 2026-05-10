[Setup]
Password=Pass12345
Encryption=yes
SetupIconFile=main.ico
AppName=PhoneShopApp
AppVersion=1.0.0
VersionInfoVersion=1.0.0
DefaultDirName={pf}\PhoneShopApp
DefaultGroupName=PhoneShopApp
OutputBaseFilename=PhoneShopApp_Installer
Compression=lzma
SolidCompression=yes
DisableDirPage=no
DisableProgramGroupPage=no

[Files]
Source: "dist\main.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "main.ico"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PhoneShopApp"; Filename: "{app}\main.exe"; WorkingDir: "{app}"

Name: "{userdesktop}\PhoneShopApp"; Filename: "{app}\main.exe"; Tasks: desktopicon; WorkingDir: "{app}"

[Tasks]
Name: desktopicon; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\main.exe"; Description: "Launch PhoneShopApp"; Flags: nowait postinstall skipifsilent
