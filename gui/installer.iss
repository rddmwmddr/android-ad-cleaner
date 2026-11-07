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

[InstallDelete]
; 0.3.2 及更早按旧产品名建了开始菜单组与桌面快捷方式；AppId 没变，装新版按升级处理，不清掉就和新的并存。
; 公共级那两条只在提权安装时删：以前可能按「所有用户」装过，而这次选了按用户装，没权限删公共目录会让安装报错。
Type: filesandordirs; Name: "{userprograms}\安卓去广告"
Type: filesandordirs; Name: "{commonprograms}\安卓去广告"; Check: IsAdminInstallMode
Type: files; Name: "{autodesktop}\安卓去广告.lnk"
Type: files; Name: "{commondesktop}\安卓去广告.lnk"; Check: IsAdminInstallMode

[Files]
Source: "dist\AndroidAdCleaner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\肉呆去广告"; Filename: "{app}\AndroidAdCleaner.exe"
Name: "{autodesktop}\肉呆去广告"; Filename: "{app}\AndroidAdCleaner.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AndroidAdCleaner.exe"; Description: "{cm:LaunchProgram,肉呆去广告}"; Flags: nowait postinstall skipifsilent
