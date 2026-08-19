; ============================================================================
;  Jsplit — Windows installer (Inno Setup)
;  Produces JsplitSetup.exe. It "fixes itself into the right spots":
;    • Jsplit.vst3   -> C:\Program Files\Common Files\VST3   (DAWs scan here)
;    • engine + python -> C:\ProgramData\Jsplit               (machine-wide)
;    • writes C:\ProgramData\Jsplit\jsplit.config             (plugin reads it)
;    • installs the Python dependencies on first install
;
;  Build it with installer\build_installer.ps1 (it stages files then calls
;  iscc on this script). Do not run iscc on this by hand unless the staging
;  folder already exists.
;
;  Expected defines (passed by build_installer.ps1 via /D...):
;    Staging   = absolute path to the staging folder
;    AppVer    = version string (e.g. 0.1.0)
;    Offline   = 1 to install deps from bundled wheels, 0 to pip from PyPI
; ============================================================================

#ifndef Staging
  #define Staging "staging"
#endif
#ifndef AppVer
  #define AppVer "0.1.0"
#endif
#ifndef Offline
  #define Offline "1"
#endif

[Setup]
AppId={{7C4B9E2A-1D6F-4E5B-9A3C-JSPLIT000001}
AppName=Jsplit
AppVersion={#AppVer}
AppPublisher=Jsplit
DefaultDirName={commonpf}\Jsplit
DefaultGroupName=Jsplit
DisableProgramGroupPage=yes
OutputBaseFilename=JsplitSetup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
ChangesEnvironment=yes
WizardStyle=modern
UninstallDisplayName=Jsplit

[Files]
; --- the plugin (VST3 is a folder bundle) ---
Source: "{#Staging}\Jsplit.vst3\*"; DestDir: "{commoncf}\VST3\Jsplit.vst3"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

; --- the Python engine (code) ---
Source: "{#Staging}\engine\*"; DestDir: "{commonappdata}\Jsplit\engine"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

; --- the bundled portable Python runtime ---
Source: "{#Staging}\python\*"; DestDir: "{commonappdata}\Jsplit\python"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

#if Offline == "1"
; --- pre-downloaded wheels for a fully offline dependency install ---
Source: "{#Staging}\wheels\*"; DestDir: "{commonappdata}\Jsplit\wheels"; \
    Flags: recursesubdirs createallsubdirs ignoreversion
#endif

[Dirs]
Name: "{commonappdata}\Jsplit\stems"; Permissions: users-modify

[Registry]
; make the engine discoverable via env vars too (config file is primary)
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: string; ValueName: "JSPLIT_HOME"; \
    ValueData: "{commonappdata}\Jsplit\engine"; Flags: preservestringtype uninsdeletevalue
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: string; ValueName: "JSPLIT_PYTHON"; \
    ValueData: "{commonappdata}\Jsplit\python\python.exe"; Flags: preservestringtype uninsdeletevalue

[Run]
#if Offline == "1"
Filename: "{commonappdata}\Jsplit\python\python.exe"; \
    Parameters: "-m pip install --no-warn-script-location --no-index --find-links ""{commonappdata}\Jsplit\wheels"" -r ""{commonappdata}\Jsplit\engine\requirements.txt"""; \
    StatusMsg: "Setting up the AI engine (offline, a few minutes)…"; \
    Flags: runhidden waituntilterminated
#else
Filename: "{commonappdata}\Jsplit\python\python.exe"; \
    Parameters: "-m pip install --no-warn-script-location -r ""{commonappdata}\Jsplit\engine\requirements.txt"""; \
    StatusMsg: "Downloading & setting up the AI engine (needs internet, several minutes)…"; \
    Flags: runhidden waituntilterminated
#endif

[UninstallDelete]
Type: filesandordirs; Name: "{commoncf}\VST3\Jsplit.vst3"
Type: filesandordirs; Name: "{commonappdata}\Jsplit"

[Code]
// After files are copied, write the config the plugin reads to locate the engine.
procedure CurStepChanged(CurStep: TSetupStep);
var
  cfgDir, cfg, py, home: String;
begin
  if CurStep = ssPostInstall then
  begin
    cfgDir := ExpandConstant('{commonappdata}\Jsplit');
    py     := ExpandConstant('{commonappdata}\Jsplit\python\python.exe');
    home   := ExpandConstant('{commonappdata}\Jsplit\engine');
    cfg    := 'python=' + py + #13#10 + 'home=' + home + #13#10;
    ForceDirectories(cfgDir);
    SaveStringToFile(cfgDir + '\jsplit.config', cfg, False);
  end;
end;
