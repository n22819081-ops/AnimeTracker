#define MyAppName "Anime Tracker"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Anime Tracker"
#define MyAppExeName "Anime Tracker.exe"

[Setup]
AppId={{927EC9E3-149D-4FB8-9016-C1CC7AC55D90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Anime Tracker
DefaultGroupName=Anime Tracker
DisableProgramGroupPage=yes
OutputDir=..\release\1.0.0
OutputBaseFilename=Anime-Tracker-Setup-1.0.0
SetupIconFile=..\assets\anime_tracker.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=none
SolidCompression=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
ChangesEnvironment=no
VersionInfoVersion=1.0.0.0
VersionInfoProductVersion=1.0.0
VersionInfoDescription=Anime Tracker Installer

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Anime Tracker\*"; DestDir: "{app}"; Excludes: "Anime Tracker.exe"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer-staging\Anime Tracker.bin"; DestDir: "{app}"; DestName: "Anime Tracker.exe"; Flags: ignoreversion

[Icons]
Name: "{group}\Anime Tracker"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\Anime Tracker"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Anime Tracker"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; User data lives under LocalAppData\Anime Tracker\AnimeTracker and is intentionally preserved.
