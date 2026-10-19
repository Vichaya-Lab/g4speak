#define AppVersion "1.3.0"

[Setup]
AppId={{B3F29956-3D69-4994-9B8D-84317FD5C621}
AppName=G4Speak
AppVersion={#AppVersion}
AppPublisher=Vichaya Lab
AppPublisherURL=https://github.com/Vichaya-Lab/g4speak
AppSupportURL=https://github.com/Vichaya-Lab/g4speak/issues
AppUpdatesURL=https://github.com/Vichaya-Lab/g4speak/releases/latest
DefaultDirName={localappdata}\Programs\G4Speak
DefaultGroupName=G4Speak
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
WizardStyle=modern
SetupIconFile=..\..\assets\logo.ico
UninstallDisplayIcon={app}\G4Speak.exe
UninstallDisplayName=G4Speak
AppMutex=Local\G4Speak.App
CloseApplications=no
RestartApplications=no
OutputDir=..\..\dist
OutputBaseFilename=G4Speak-Setup-{#AppVersion}
Compression=lzma2/fast
SolidCompression=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\dist\G4Speak.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\G4Speak"; Filename: "{app}\G4Speak.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\G4Speak"; Filename: "{app}\G4Speak.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\G4Speak.exe"; Description: "Launch G4Speak"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  StartupCommand: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    // Remove autostart only when it points at this installation, not a portable copy.
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
      'G4Speak', StartupCommand) then
      if CompareText(StartupCommand, '"' + ExpandConstant('{app}\G4Speak.exe') + '"') = 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'G4Speak');
  end;
end;
