; ============================================================
; JK Catalog Multi — Inno Setup Installer Script
; ============================================================
; Version:  1.0.0 (First Release)
; Built:    May 2026
; Publisher: JK Hardware
;
; BUILD:
;   1. Run: pyinstaller JK_Catalog_Multi.spec --noconfirm
;   2. Open this file in Inno Setup Compiler
;   3. Click Build → Compile (Ctrl+F9)
;   Output: dist\JK_Catalog_Multi_Setup.exe
; ============================================================

#define MyAppName "JK Catalog Multi"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "JK Hardware"
#define MyAppExeName "JK_Catalog_Multi.exe"
#define MyAppCopyright "Copyright © 2026 JK Hardware"

[Setup]
; --- App Identity ---
AppId={{B8F2D4A1-7C3E-4E5A-9D1F-6A2B8C4E0F3D}
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
OutputBaseFilename=JK_Catalog_Multi_Setup

; --- Compression ---
Compression=lzma2/max
SolidCompression=yes

; --- Appearance ---
SetupIconFile=JK_Icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
WizardSizePercent=110,110

; --- License ---
LicenseFile=LICENSE.txt

; --- Privileges ---
; Admin required for Program Files install + public desktop shortcuts
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64compatible

; --- Misc ---
; Show "Setup has finished" page
ShowTasksTreeLines=yes
AllowNoIcons=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; Customize the welcome page text
WelcomeLabel1=Welcome to {#MyAppName} Setup
WelcomeLabel2=This will install {#MyAppName} version {#MyAppVersion} on your computer.%n%nThis application requires Microsoft SQL Server Express to be installed and running.%n%nIt is recommended that you close all other applications before continuing.
FinishedLabel=Setup has completed installing {#MyAppName} on your computer.%n%nThe application may be launched from the Start Menu or Desktop shortcut.

[Tasks]
; Desktop shortcut (checked by default)
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; --- Main Executable ---
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; --- Application Icon ---
Source: "JK_Icon.ico"; DestDir: "{app}"; Flags: ignoreversion

; --- License (installed alongside for reference) ---
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

; --- Config Files (user may need these alongside the EXE) ---
Source: "config\cleaning_rules.json"; DestDir: "{app}\config"; Flags: ignoreversion onlyifdoesntexist
Source: "config\catalog_config.json"; DestDir: "{app}\config"; Flags: ignoreversion onlyifdoesntexist

[Icons]
; Start Menu
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\JK_Icon.ico"; Comment: "Launch {#MyAppName}"

; Public Desktop (visible to ALL RDP users on this machine)
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\JK_Icon.ico"

; Start Menu — Uninstall shortcut
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\JK_Icon.ico"; Comment: "Uninstall {#MyAppName}"

[Run]
; Launch after install (optional checkbox)
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent runascurrentuser

[UninstallDelete]
; Clean up build artifacts left in app directory (logs, caches)
Type: files; Name: "{app}\error.log"
Type: dirifempty; Name: "{app}\config"
Type: dirifempty; Name: "{app}"

[Code]
// ============================================================
// Pre-install check: Warn if SQL Server Express is not detected
// ============================================================
function IsSQLServerInstalled: Boolean;
var
  ResultCode: Integer;
begin
  // Check if sqlservr.exe process exists or MSSQL service is registered
  Result := RegKeyExists(HKLM, 'SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL');
end;

procedure InitializeWizard;
begin
  // Optional: Add a pre-check for SQL Server
  if not IsSQLServerInstalled then
  begin
    MsgBox(
      'Microsoft SQL Server was not detected on this machine.' + #13#10 + #13#10 +
      'JK Catalog Multi requires SQL Server Express (or higher) to function.' + #13#10 +
      'Please install SQL Server Express before running this application.' + #13#10 + #13#10 +
      'The installer will continue, but the application will not work until SQL Server is available.',
      mbInformation, MB_OK
    );
  end;
end;

// Prevent downgrade installs
function InitializeSetup: Boolean;
var
  InstalledVersion: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM,
    'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{{B8F2D4A1-7C3E-4E5A-9D1F-6A2B8C4E0F3D}_is1',
    'DisplayVersion', InstalledVersion) then
  begin
    if CompareStr(InstalledVersion, '{#MyAppVersion}') > 0 then
    begin
      MsgBox('A newer version (' + InstalledVersion + ') is already installed.' + #13#10 +
             'Please uninstall it first if you want to downgrade.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
