; PRESSFLOW 설치 파일(Inno Setup). CI에서 /DAppVersion=x.y.z 로 컴파일한다.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B1D6F58-1C3E-4F6C-9E52-505245535346}
AppName=PRESSFLOW
AppVersion={#AppVersion}
AppPublisher=강원사회복지신문
DefaultDirName={localappdata}\Programs\PRESSFLOW
DefaultGroupName=PRESSFLOW
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=PRESSFLOW-Setup-{#AppVersion}
SetupIconFile=..\static\icons\pressflow.ico
UninstallDisplayIcon={app}\PRESSFLOW.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64compatible

#ifdef HAVEKOREAN
[Languages]
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"
#endif

[Files]
Source: "..\dist\PRESSFLOW\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autodesktop}\PRESSFLOW"; Filename: "{app}\PRESSFLOW.exe"; Parameters: "run --open"
Name: "{autoprograms}\PRESSFLOW"; Filename: "{app}\PRESSFLOW.exe"; Parameters: "run --open"
Name: "{userstartup}\PRESSFLOW 자동시작"; Filename: "{app}\PRESSFLOW.exe"; Parameters: "run"

[Run]
; 처음 설치: 창을 연다 / 자동 업데이트(조용한 설치): 백그라운드로만 다시 시작(열려 있던 화면은 스스로 새로고침)
Filename: "{app}\PRESSFLOW.exe"; Parameters: "run --open"; Description: "PRESSFLOW 시작"; Flags: nowait postinstall skipifsilent
Filename: "{app}\PRESSFLOW.exe"; Parameters: "run"; Flags: nowait runasoriginaluser; Check: WizardSilent
