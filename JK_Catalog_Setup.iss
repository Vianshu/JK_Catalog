; ============================================================
; JK Catalog (Single-User) — Inno Setup Installer Script
; ============================================================
; Version:  1.0.0
; Publisher: JK Hardware
;
; BUILD:
;   1. Run: pyinstaller JK_Catalog.spec --noconfirm
;   2. Open this file in Inno Setup Compiler
;   3. Click Build → Compile (Ctrl+F9)
;   Output: dist\JK_Catalog_Setup.exe
; ============================================================

#define MyAppName "JK Catalog"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "JK Hardware"
#define MyAppExeName "JK_Catalog.exe"
#define MyAppCopyright "Copyright © 2026 JK Hardware"

[Setup]
; --- App Identity ---
AppId={{A1C3E5D7-2B4F-4A6C-8E0D-5F7A9B1C3E5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright={#MyAppCopyright}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
VersionInfoCopyright={#MyAppCopyright}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

; --- Installation Directories ---
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; --- Output ---
OutputDir=dist
OutputBaseFilename=JK_Catalog_Setup

; --- Compression ---
Compression=lzma2/max
SolidCompression=yes

; --- Appearance ---
SetupIconFile=JK_Icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
WizardSizePercent=110,110
WizardImageFile=WizardImageFile.bmp
WizardSmallImageFile=WizardSmallImageFile.bmp

; --- License ---
LicenseFile=LICENSE.txt

; --- Privileges ---
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64compatible

; --- Misc ---
ShowTasksTreeLines=yes
AllowNoIcons=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to {#MyAppName} Setup
WelcomeLabel2=This will install {#MyAppName} version {#MyAppVersion} on your computer.%n%nIt is recommended that you close all other applications before continuing.
FinishedLabel=Setup has completed installing {#MyAppName} on your computer.%n%nThe application may be launched from the Start Menu or Desktop shortcut.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; --- All application files (one-dir build output) ---
Source: "dist\JK_Catalog\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; --- Icon ---
Source: "JK_Icon.ico"; DestDir: "{app}"; Flags: ignoreversion

; --- License ---
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\JK_Icon.ico"; Comment: "Launch {#MyAppName}"

; Desktop shortcut
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\JK_Icon.ico"

; Uninstall shortcut
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\JK_Icon.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runascurrentuser

[UninstallDelete]
Type: files; Name: "{app}\error.log"
Type: dirifempty; Name: "{app}"
