; Instalador gráfico de PoorSDR4All para Windows (Inno Setup 6).
; Parámetros (ISCC /D...): AppVersion, DistDir (salida de PyInstaller), PayloadDir (poorsdr4all-<v>.tar.gz),
;                          AddonsDir (complementos: rtty, libro, *-lic), LicenseFile, ToolsDir (preparar-wsl.ps1),
;                          IconFile, OutDir
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B2D1B3A4-7C5E-4F0A-9E61-3C8A5D7F2B90}
AppName=PoorSDR4All
AppVersion={#AppVersion}
AppVerName=PoorSDR4All {#AppVersion}
AppPublisher=Acuantico Power
AppPublisherURL=https://acuanticopower.com/poorsdr4all/
AppSupportURL=https://github.com/Acuantico/poorsdr4all/issues
AppUpdatesURL=https://github.com/Acuantico/poorsdr4all/releases
DefaultDirName={autopf}\PoorSDR4All
DefaultGroupName=PoorSDR4All
DisableProgramGroupPage=yes
LicenseFile={#LicenseFile}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\PoorSDR4All.exe
OutputDir={#OutDir}
OutputBaseFilename=poorsdr4all-installer-{#AppVersion}-windows-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no
ChangesEnvironment=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
es.TipoCompleto=Instalación completa (recomendada)
es.TipoPersonal=Instalación personalizada
es.CompApp=PoorSDR4All (aplicación)
es.CompOwrx=OpenWebRX+ (cascada), con WSL2 · recomendado
es.CompUsb=Soporte para SDR por USB (usbipd-win)
es.CompRtty=RTTY Power (decodificador y transmisión RTTY)
es.CompLibro=Libro de guardia (NMN1M)
es.IconoLibro=Crear un icono del Libro de guardia en el escritorio
es.NombreLibro=Libro de guardia (NMN1M)
es.PreparandoWsl=Preparando WSL2 (puede tardar unos minutos)...
es.InstalarOwrx=Instalar OpenWebRX+ ahora (recomendado; tarda unos 30 minutos la primera vez)
es.ReparaOwrx=Reparar OpenWebRX+ (WSL)
es.WslFallo=No se pudo preparar WSL2 automáticamente.%n%nPoorSDR4All se ha instalado igualmente. Puedes reintentarlo más tarde con «Reparar OpenWebRX+» en el menú Inicio.%n%nDetalle: C:\ProgramData\PoorSDR4All\preparar-wsl.log
es.WslAntiguo=Tu versión de Windows es demasiado antigua para WSL2 (hace falta Windows 10 versión 2004 o posterior).%n%nPoorSDR4All se instalará, pero sin OpenWebRX+.
es.QuitarOwrx=¿Quieres eliminar también OpenWebRX+ y su sistema Linux (WSL) de PoorSDR4All?%n%nSe liberará el espacio que ocupan (varios GB). Tus otras distribuciones de WSL no se tocan.
en.TipoCompleto=Full installation (recommended)
en.TipoPersonal=Custom installation
en.CompApp=PoorSDR4All (application)
en.CompOwrx=OpenWebRX+ (waterfall), with WSL2 · recommended
en.CompUsb=USB SDR support (usbipd-win)
en.CompRtty=RTTY Power (RTTY decoder and transmitter)
en.CompLibro=Station logbook (NMN1M)
en.IconoLibro=Create a desktop icon for the station logbook
en.NombreLibro=Station logbook (NMN1M)
en.PreparandoWsl=Preparing WSL2 (this can take a few minutes)...
en.InstalarOwrx=Install OpenWebRX+ now (recommended; takes about 30 minutes the first time)
en.ReparaOwrx=Repair OpenWebRX+ (WSL)
en.WslFallo=WSL2 could not be prepared automatically.%n%nPoorSDR4All was installed anyway. You can retry later with "Repair OpenWebRX+" in the Start menu.%n%nDetails: C:\ProgramData\PoorSDR4All\preparar-wsl.log
en.WslAntiguo=This version of Windows is too old for WSL2 (Windows 10 version 2004 or later is required).%n%nPoorSDR4All will be installed, but without OpenWebRX+.
en.QuitarOwrx=Do you also want to remove OpenWebRX+ and its Linux system (WSL) for PoorSDR4All?%n%nThis frees the space they use (several GB). Your other WSL distributions are not touched.

[Types]
Name: "full"; Description: "{cm:TipoCompleto}"
Name: "custom"; Description: "{cm:TipoPersonal}"; Flags: iscustom

[Components]
Name: "app"; Description: "{cm:CompApp}"; Types: full custom; Flags: fixed
Name: "owrx"; Description: "{cm:CompOwrx}"; Types: full
Name: "usb"; Description: "{cm:CompUsb}"; Types: full
Name: "rtty"; Description: "{cm:CompRtty}"; Types: full
Name: "libro"; Description: "{cm:CompLibro}"; Types: full

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Components: app
Name: "desktopicon_libro"; Description: "{cm:IconoLibro}"; Components: libro

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: app
Source: "{#PayloadDir}\poorsdr4all-*.tar.gz"; DestDir: "{app}\payload"; Flags: ignoreversion; Components: owrx
Source: "{#ToolsDir}\preparar-wsl.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: owrx
Source: "{#ToolsDir}\sdr-ids.txt"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: usb
Source: "{#LicenseFile}"; DestDir: "{app}\licenses"; Flags: ignoreversion; Components: app
; Complementos: son paquetes Python que la consola descubre por sus metadatos (entry points) dentro de _internal.
Source: "{#AddonsDir}\fuente-lic\*"; DestDir: "{app}\licenses\7LED"; Flags: ignoreversion; Components: app
Source: "{#AddonsDir}\rtty\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: rtty
Source: "{#AddonsDir}\rtty-lic\*"; DestDir: "{app}\licenses\rtty-power"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: rtty
Source: "{#AddonsDir}\libro\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: libro
Source: "{#AddonsDir}\libro-lic\*"; DestDir: "{app}\licenses\nmn1m"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: libro

[Icons]
Name: "{autoprograms}\PoorSDR4All\PoorSDR4All"; Filename: "{app}\PoorSDR4All.exe"; Components: app
Name: "{autoprograms}\PoorSDR4All\{cm:ReparaOwrx}"; Filename: "{app}\PoorSDR4All.exe"; Parameters: "--reparar-owrx"; Components: owrx
Name: "{autodesktop}\PoorSDR4All"; Filename: "{app}\PoorSDR4All.exe"; Tasks: desktopicon
; El Libro de guardia también se abre solo, con su propio icono (el que trae NMN1M).
Name: "{autoprograms}\PoorSDR4All\{cm:NombreLibro}"; Filename: "{app}\PoorSDR4All.exe"; Parameters: "--libro-guardia"; IconFilename: "{app}\_internal\poorsdr_libro_guardia\assets\app_icon.ico"; Components: libro
Name: "{autodesktop}\{cm:NombreLibro}"; Filename: "{app}\PoorSDR4All.exe"; Parameters: "--libro-guardia"; IconFilename: "{app}\_internal\poorsdr_libro_guardia\assets\app_icon.ico"; Tasks: desktopicon_libro; Components: libro

[Run]
Filename: "{app}\PoorSDR4All.exe"; Parameters: "--asistente-wsl"; Description: "{cm:InstalarOwrx}"; Flags: nowait postinstall skipifsilent runasoriginaluser; Components: owrx; Check: PuedeInstalarOwrxAhora
Filename: "{app}\PoorSDR4All.exe"; Description: "{cm:LaunchProgram,PoorSDR4All}"; Flags: nowait postinstall skipifsilent unchecked runasoriginaluser; Components: app

[Code]
var
  ReinicioWsl: Boolean;
  WslListo: Boolean;

function NeedRestart(): Boolean;
begin
  Result := ReinicioWsl;
end;

function PuedeInstalarOwrxAhora(): Boolean;
begin
  Result := WslListo and (not ReinicioWsl);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Codigo: Integer;
  Parametros, Script: String;
begin
  if (CurStep = ssPostInstall) and WizardIsComponentSelected('owrx') then
  begin
    WizardForm.StatusLabel.Caption := CustomMessage('PreparandoWsl');
    WizardForm.ProgressGauge.Style := npbstMarquee;
    Script := ExpandConstant('{app}\tools\preparar-wsl.ps1');
    Parametros := '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + Script + '"';
    if WizardIsComponentSelected('usb') then
      Parametros := Parametros + ' -Usbipd';
    if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parametros, '',
            SW_HIDE, ewWaitUntilTerminated, Codigo) then
    begin
      case Codigo of
        0:  WslListo := True;
        10: begin
              WslListo := True;
              ReinicioWsl := True;
              { al volver a iniciar sesión, el asistente continúa solo con la instalación de OpenWebRX+ }
              RegWriteStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\RunOnce', 'PoorSDR4AllOwrx',
                '"' + ExpandConstant('{app}\PoorSDR4All.exe') + '" --asistente-wsl');
            end;
        20: MsgBox(CustomMessage('WslAntiguo'), mbInformation, MB_OK);
      else
        MsgBox(CustomMessage('WslFallo'), mbError, MB_OK);
      end;
    end
    else
      MsgBox(CustomMessage('WslFallo'), mbError, MB_OK);
    WizardForm.ProgressGauge.Style := npbstNormal;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Codigo: Integer;
begin
  if (CurUninstallStep = usUninstall) and (not UninstallSilent) then
  begin
    if MsgBox(CustomMessage('QuitarOwrx'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      Exec(ExpandConstant('{sys}\wsl.exe'), '--unregister PoorSDR4All', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
      DelTree(ExpandConstant('{localappdata}\poorsdr\wsl'), True, True, True);
    end;
  end;
end;
