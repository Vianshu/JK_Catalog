[Setup]
; Basic App Info
AppName=JK Catalog Multi
AppVersion=1.0.0
AppPublisher=JK Enterprises

; Installation Directories
DefaultDirName={autopf}\JK Catalog Multi
DefaultGroupName=JK Catalog Multi

; Output Settings
OutputDir=dist
OutputBaseFilename=JK_Catalog_Multi_Setup

; Compression
Compression=lzma2/max
SolidCompression=yes

; Look and Feel
SetupIconFile=JK_Icon.ico
UninstallDisplayIcon={app}\JK_Catalog_Multi.exe

; Required Privileges
; Admin is required to install into C:\Program Files and create public desktop shortcuts
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64

[Tasks]
; Desktop shortcut task (enabled by default)
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Main Executable
Source: "dist\JK_Catalog_Multi.exe"; DestDir: "{app}"; Flags: ignoreversion
; Icon for the uninstaller/shortcuts
Source: "JK_Icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu Icon
Name: "{group}\JK Catalog Multi"; Filename: "{app}\JK_Catalog_Multi.exe"; IconFilename: "{app}\JK_Icon.ico"
; Public Desktop Icon (shows up for ALL RDP Users)
Name: "{commondesktop}\JK Catalog Multi"; Filename: "{app}\JK_Catalog_Multi.exe"; Tasks: desktopicon; IconFilename: "{app}\JK_Icon.ico"

[Run]
; Launch App Checkbox at the end of installation
Filename: "{app}\JK_Catalog_Multi.exe"; Description: "{cm:LaunchProgram,JK Catalog Multi}"; Flags: nowait postinstall skipifsilent
