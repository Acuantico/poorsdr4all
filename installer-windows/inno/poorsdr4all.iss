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
es.CompAv=Códec de audio (PyAV con FFmpeg) · se descarga de PyPI (unos 27 MB)
es.DescargaTitulo=Descargando un componente
es.DescargaTexto=Descargando PyAV (audio del acceso web y mp3 de las macros) desde PyPI...
es.ErrorDescarga=No se pudo descargar el códec de audio (PyAV).%n%n%1%n%n¿Quieres continuar sin él? El acceso web remoto y los mp3 de las macros no funcionarán hasta que lo instales. Las macros en WAV sí.
es.ErrorExtraer=No se pudo instalar el códec de audio descargado. Se continúa sin él.
es.NotaAv=Se descargará de Internet (PyPI) el componente PyAV, que incluye FFmpeg. Se comprueba su huella SHA-256 y no forma parte de este instalador.
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
en.CompAv=Audio codec (PyAV with FFmpeg) · downloaded from PyPI (about 27 MB)
en.DescargaTitulo=Downloading a component
en.DescargaTexto=Downloading PyAV (web access audio and macro mp3 files) from PyPI...
en.ErrorDescarga=The audio codec (PyAV) could not be downloaded.%n%n%1%n%nDo you want to continue without it? Remote web access and mp3 macros will not work until you install it. WAV macros will.
en.ErrorExtraer=The downloaded audio codec could not be installed. Continuing without it.
en.NotaAv=The PyAV component, which includes FFmpeg, will be downloaded from the Internet (PyPI). Its SHA-256 hash is verified and it is not part of this installer.
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
Name: "av"; Description: "{cm:CompAv}"; Types: full

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Components: app
Name: "desktopicon_libro"; Description: "{cm:IconoLibro}"; Components: libro

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: app
Source: "{#PayloadDir}\poorsdr4all-*.tar.gz"; DestDir: "{app}\payload"; Flags: ignoreversion; Components: owrx
Source: "{#ToolsDir}\preparar-wsl.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: owrx
Source: "{#ToolsDir}\sdr-ids.txt"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: usb
Source: "{#LicenseFile}"; DestDir: "{app}\licenses"; Flags: ignoreversion; Components: app
; THIRD_PARTY_NOTICES.md, LICENSES\ y LICENCIAS-DEPENDENCIAS.txt (generado en cada compilación con lo que PyInstaller empaqueta).
Source: "{#AddonsDir}\licencias\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: app
; Complementos: son paquetes Python que la consola descubre por sus metadatos (entry points) dentro de _internal.
Source: "{#AddonsDir}\fuente-lic\*"; DestDir: "{app}\licenses\7LED"; Flags: ignoreversion; Components: app
Source: "{#AddonsDir}\rtty\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: rtty
Source: "{#AddonsDir}\rtty-lic\*"; DestDir: "{app}\licenses\rtty-power"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: rtty
Source: "{#AddonsDir}\libro\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: libro
Source: "{#AddonsDir}\libro-lic\*"; DestDir: "{app}\licenses\nmn1m"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: libro

[InstallDelete]
; Al actualizar desde una versión anterior (1.0.0a4 llevaba PyAV/FFmpeg dentro del ejecutable) se retira lo que ya
; no se distribuye dentro: ahora PyAV se descarga en «extras» y no debe quedar una copia vieja en _internal.
Type: filesandordirs; Name: "{app}\_internal\av"
Type: filesandordirs; Name: "{app}\_internal\av.libs"
Type: filesandordirs; Name: "{app}\_internal\av-*.dist-info"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\extras"

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
const
  // PyAV 17.1.0 (compatible con aiortc 1.x). Rueda oficial de PyPI para Windows x64 (abi3: sirve para Python 3.12).
  // URL y SHA-256 comprobados contra https://pypi.org/pypi/av/17.1.0/json. PyAV trae FFmpeg, cuyas bibliotecas son
  // LGPL y, según la compilación, incluyen códecs GPL (x264/x265): por eso NO va dentro del instalador.
  AvUrl = 'https://files.pythonhosted.org/packages/6b/f2/53a7cd34adb6a971d7e6d99663e74db286966c9db8afdca17472fdf0f98e/av-17.1.0-cp311-abi3-win_amd64.whl';
  AvSha256 = '5df5c1172ef1cf65a1529d612f7da7798ce2cf82c1ff7212466b538a6cc7214c';
  AvFichero = 'av-componente.zip';   // una rueda es un .zip

var
  ReinicioWsl: Boolean;
  WslListo: Boolean;
  DescargaPagina: TDownloadWizardPage;
  AvOmitido: Boolean;

procedure InitializeWizard;
begin
  DescargaPagina := CreateDownloadPage(CustomMessage('DescargaTitulo'), CustomMessage('DescargaTexto'), nil);
end;

// Descarga la rueda de PyAV comprobando su SHA-256. Si falla, ofrece seguir sin el componente.
function DescargarAv: Boolean;
var
  Detalle: String;
begin
  Result := FileExists(ExpandConstant('{tmp}\' + AvFichero));
  if Result then
    Exit;
  DescargaPagina.Clear;
  DescargaPagina.Add(AvUrl, AvFichero, AvSha256);
  DescargaPagina.Show;
  try
    try
      DescargaPagina.Download;
      Result := True;
    except
      Detalle := GetExceptionMessage;
      Result := False;
    end;
  finally
    DescargaPagina.Hide;
  end;
  if not Result then
    AvOmitido := SuppressibleMsgBox(FmtMessage(CustomMessage('ErrorDescarga'), [Detalle]),
      mbError, MB_YESNO or MB_DEFBUTTON2, IDYES) = IDYES;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  // Se descarga antes de copiar nada: si no hay conexión, el usuario decide antes de que se instale a medias.
  if (CurPageID = wpReady) and WizardIsComponentSelected('av') then
  begin
    if not DescargarAv then
      Result := AvOmitido;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine + MemoTypeInfo + NewLine + NewLine + MemoComponentsInfo
    + NewLine + NewLine + MemoGroupInfo + NewLine + NewLine + MemoTasksInfo;
  if WizardIsComponentSelected('av') then
    Result := Result + NewLine + NewLine + CustomMessage('NotaAv');
end;

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
  Parametros, Script, Zip, Destino: String;
begin
  if (CurStep = ssInstall) and WizardIsComponentSelected('av') and (not AvOmitido) then
  begin
    // Instalación silenciosa: no pasa por la página "Listo para instalar", así que se descarga aquí.
    if DescargarAv then
    begin
      Zip := ExpandConstant('{tmp}\' + AvFichero);
      StringChangeEx(Zip, '''', '''''', True);
      Destino := ExpandConstant('{app}\extras');
      ForceDirectories(Destino);
      if (not Exec('powershell.exe',
            '-NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ''' + Zip +
            ''' -DestinationPath ''' + Destino + ''' -Force"',
            '', SW_HIDE, ewWaitUntilTerminated, Codigo))
         or (Codigo <> 0) or (not FileExists(Destino + '\av\__init__.py')) then
        SuppressibleMsgBox(CustomMessage('ErrorExtraer'), mbError, MB_OK, IDOK);
    end;
  end;
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
