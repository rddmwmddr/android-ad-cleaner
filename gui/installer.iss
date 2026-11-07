; Windows 安装程序（Inno Setup 6）。由 GitHub Actions 调用：iscc /DAPPVER=0.1.0 gui\installer.iss
#ifndef APPVER
  #define APPVER "0.0.0"
#endif
[Setup]
AppId={{6C1E3F2A-8B7D-4E55-9A41-AAC0ADC1EA01}
AppName=肉呆去广告
AppVersion={#APPVER}
AppPublisher=android-ad-cleaner
AppPublisherURL=https://github.com/rddmwmddr/android-ad-cleaner
DefaultDirName={autopf}\AndroidAdCleaner
DefaultGroupName=肉呆去广告
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=AndroidAdCleaner-{#APPVER}-windows-setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\AndroidAdCleaner.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
#if FileExists(AddBackslash(SourcePath) + "ChineseSimplified.isl")
Name: "zh"; MessagesFile: "ChineseSimplified.isl"
#else
Name: "en"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\AndroidAdCleaner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\肉呆去广告"; Filename: "{app}\AndroidAdCleaner.exe"
Name: "{autodesktop}\肉呆去广告"; Filename: "{app}\AndroidAdCleaner.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AndroidAdCleaner.exe"; Description: "{cm:LaunchProgram,肉呆去广告}"; Flags: nowait postinstall skipifsilent
