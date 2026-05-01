; -- AI_Media_Suite_Installer_English.iss --
; Optimized for AI Media Suite (Non-Admin & High Compression)

[Setup]
AppName=AI Media Suite
AppVersion=2.0.0
AppPublisher=Minta1234
DefaultDirName={userappdata}\AIMediaSuite
DefaultGroupName=AI Media Suite
OutputDir=.\Installer
OutputBaseFilename=AI_Media_Suite_Setup

; --- ICON FIX: Points to root folder ---
SetupIconFile=icon.ico 

Compression=lzma2/ultra64
SolidCompression=yes
InternalCompressLevel=ultra
PrivilegesRequired=lowest
CloseApplications=yes
CloseApplicationsFilter=*.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; --- ICON FIX: Copies icon from root folder to the install directory ---
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion 

[Icons]
Name: "{group}\AI Media Suite"; Filename: "{app}\app.exe"; IconFilename: "{app}\icon.ico"
Name: "{userdesktop}\AI Media Suite"; Filename: "{app}\app.exe"; Tasks: desktopicon; IconFilename: "{app}\icon.ico"

[Run]
Filename: "{app}\app.exe"; Description: "{cm:LaunchProgram,AI Media Suite}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\downloads"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if DirExists(ExpandConstant('{app}')) then
      DelTree(ExpandConstant('{app}'), True, True, True);
  end;
end;

[Messages]
ConfirmUninstall=Are you sure you want to completely remove %1 and all of its components?
