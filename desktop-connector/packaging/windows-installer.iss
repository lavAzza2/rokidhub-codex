#ifndef AppVersion
  #define AppVersion "0.6.0-beta.6"
#endif
#ifndef SourceDir
  #error SourceDir must point to the PyInstaller onedir output
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef OutputBaseFilename
  #define OutputBaseFilename "RokidHub-Desktop-Connector-setup"
#endif

[Setup]
AppId={{C496E04A-4D79-48D6-A4B8-F0B3D0B88280}
AppName=RokidHub Desktop Connector
AppVersion={#AppVersion}
AppPublisher=RokidHub
AppPublisherURL=https://rokidhub.com/
AppSupportURL=https://github.com/lavAzza2/rokidhub-codex/issues
AppUpdatesURL=https://github.com/lavAzza2/rokidhub-codex/releases/latest
DefaultDirName={localappdata}\Programs\RokidHub Desktop Connector
DefaultGroupName=RokidHub
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile={#SourceDir}\_internal\rokidhub_desktop_connector\assets\favicon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
AppMutex=RokidHubDesktopConnectorGui
UninstallDisplayIcon={app}\RokidHub Desktop Connector.exe
VersionInfoVersion=0.6.0.6
VersionInfoCompany=RokidHub
VersionInfoDescription=RokidHub Desktop Connector Setup
VersionInfoProductName=RokidHub Desktop Connector
VersionInfoProductVersion=0.6.0.6

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\RokidHub Desktop Connector"; Filename: "{app}\RokidHub Desktop Connector.exe"
Name: "{userdesktop}\RokidHub Desktop Connector"; Filename: "{app}\RokidHub Desktop Connector.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
Filename: "{app}\RokidHub Desktop Connector.exe"; Description: "{cm:LaunchProgram,RokidHub Desktop Connector}"; Flags: nowait postinstall skipifsilent
