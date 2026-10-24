# Construye el instalador de PoorSDR4All para Windows (se ejecuta DENTRO de la VM de Windows).
# Entrada: el servidor del anfitrión sirve build-src.zip (código publicado + este instalador + paquete OpenWebRX+).
# Salida: poorsdr4all-installer-<versión>-windows-x64.exe y el registro, subidos al anfitrión.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$h = "http://192.168.122.1:8099"
$W = "C:\lab\build"
function Paso($t) { "`n=== $t ({0:HH:mm:ss}) ===" -f (Get-Date) }
function X { $e, $r = $args; & $e @r; if ($LASTEXITCODE) { throw "Fallo ($LASTEXITCODE): $e $r" } }
function Subir($nombre, $ruta) { Invoke-WebRequest "$h/subir/$nombre" -Method Put -InFile $ruta -UseBasicParsing -TimeoutSec 900 | Out-Null }

Paso "Preparando carpeta de trabajo"
Get-Process PoorSDR4All -ErrorAction SilentlyContinue | Stop-Process -Force
if (Test-Path "$W\src") { Remove-Item "$W\src" -Recurse -Force }
New-Item -ItemType Directory -Force $W | Out-Null
Set-Location $W   # PyInstaller se niega a correr desde C:\WINDOWS\system32
Invoke-WebRequest "$h/build-src.zip" -OutFile "$W\build-src.zip" -UseBasicParsing
Expand-Archive "$W\build-src.zip" "$W\src" -Force
$R = "$W\src\poorsdr4all"; $I = "$W\src\installer"; $P = "$W\src\payload"
$V = ([regex]::Match((Get-Content "$R\pyproject.toml" -Raw), '(?m)^version\s*=\s*"([^"]+)"')).Groups[1].Value
"Versión: $V"

Paso "Python 3.12"
$SP = @("$env:ProgramFiles\Python312\python.exe", "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (!$SP) { throw "No hay Python 3.12 en la VM" }
"Python: $SP"

Paso "Entorno virtual y dependencias"
if (-not (Test-Path "$W\venv\Scripts\python.exe")) { X $SP -m venv "$W\venv" }
$Py = "$W\venv\Scripts\python.exe"
X $Py -m pip install -q -U pip wheel pyinstaller
X $Py -m pip install -q --force-reinstall --no-deps $R
# Los extras [web] (websockets, fastapi, uvicorn, aiortc...) son los que install.sh instala por defecto en Linux;
# la cascada necesita websockets para hablar con OpenWebRX+.
X $Py -m pip install -q "$R[web]"
$paquete = (& $Py -c "import poorsdr,os;print(os.path.dirname(poorsdr.__file__))").Trim()
"poorsdr instalado en: $paquete"

Paso "Complementos: RTTY Power y Libro de guardia (NMN1M)"
# Se instalan en el entorno solo para tener su código y metadatos; PyInstaller NO los incluye en el programa base
# (la consola los descubre por entry points), así que el instalador puede ofrecerlos como opcionales.
X $Py -m pip install -q "$R\plugins\rtty-power"
if (Test-Path "$W\nmn1m") { Remove-Item "$W\nmn1m" -Recurse -Force }
New-Item -ItemType Directory -Force "$W\nmn1m" | Out-Null
X tar.exe -xzf "$W\src\addons-src\nmn1m.tar.gz" -C "$W\nmn1m"
$nmn = (Get-ChildItem "$W\nmn1m" -Directory | Select-Object -First 1).FullName
X $Py -m pip install -q $nmn
$sp = (& $Py -c "import sysconfig;print(sysconfig.get_paths()['purelib'])").Trim()
$A = "$W\addons"
if (Test-Path $A) { Remove-Item $A -Recurse -Force }
foreach ($par in @(@("rtty", "poorsdr_rtty_power"), @("libro", "poorsdr_libro_guardia"))) {
    $dest = "$A\$($par[0])"; New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item "$sp\$($par[1])" $dest -Recurse
    Get-ChildItem "$sp" -Directory -Filter "$($par[1])-*.dist-info" | ForEach-Object { Copy-Item $_.FullName $dest -Recurse }
    Get-ChildItem $dest -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    "{0}: {1}" -f $par[0], ((Get-ChildItem $dest | ForEach-Object Name) -join ", ")
}
New-Item -ItemType Directory -Force "$A\rtty-lic", "$A\libro-lic", "$A\fuente-lic" | Out-Null
Copy-Item "$R\src\poorsdr\ui\assets\fonts\7LED-*.txt" "$A\fuente-lic\"
Copy-Item "$R\plugins\rtty-power\LICENSE" "$A\rtty-lic\"
Copy-Item "$nmn\LICENSE", "$nmn\DATA_PROVENANCE.md" "$A\libro-lic\"
if (Test-Path "$nmn\LICENSES") { Copy-Item "$nmn\LICENSES" "$A\libro-lic\LICENSES" -Recurse }

Paso "Avisos y licencias de terceros que viajan con el instalador"
# PyAV (FFmpeg) NO va en el ejecutable: lo descarga el instalador. Todo lo demás que PyInstaller empaqueta
# debe llevar su aviso y su texto de licencia: se generan a partir de las dependencias reales de este entorno.
$L = "$A\licencias"; New-Item -ItemType Directory -Force $L | Out-Null
Copy-Item "$R\THIRD_PARTY_NOTICES.md" $L
Copy-Item "$R\LICENSES" "$L\LICENSES" -Recurse
X $Py "$I\build\licencias_empaquetadas.py" "$L\LICENCIAS-DEPENDENCIAS.txt" "poorsdr4all[web]" "poorsdr-rtty-power" "poorsdr-libro-guardia" --excluir av

Paso "Módulos que usan los complementos (se ejecutan como scripts aparte: PyInstaller no los ve)"
@'
import ast, pathlib, sys
mods = set()
for raiz in sys.argv[1:]:
    for f in pathlib.Path(raiz).rglob("*.py"):
        try:
            arbol = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for n in ast.walk(arbol):
            if isinstance(n, ast.Import):
                mods.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods.add(n.module)
propios = ("poorsdr", "poorsdr_libro_guardia", "poorsdr_rtty_power")
print("\n".join(sorted(m for m in mods if m.split(".")[0] not in propios)))
'@ | Set-Content "$W\modulos_complementos.py" -Encoding UTF8
$ocultos = @(& $Py "$W\modulos_complementos.py" "$A\libro\poorsdr_libro_guardia" "$A\rtty\poorsdr_rtty_power" | Where-Object { $_ })
"{0} módulos: {1}" -f $ocultos.Count, ($ocultos -join ", ")
if ($ocultos -notcontains "sqlite3") { throw "La lista de módulos de los complementos no incluye sqlite3: algo falló al leerlos" }

Paso "Icono"
X $Py -c "import sys;from PIL import Image;Image.open(sys.argv[1]).convert('RGBA').save(sys.argv[2],sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])" "$paquete\ui\assets\images\image.png" "$W\poorsdr.ico"

Paso "PyInstaller"
if (Test-Path "$W\dist") { Remove-Item "$W\dist" -Recurse -Force }
$piargs = @("--noconfirm", "--clean", "--onedir", "--windowed", "--name", "PoorSDR4All",
    "--icon", "$W\poorsdr.ico", "--paths", "$I\src",
    "--distpath", "$W\dist", "--workpath", "$W\pyi", "--specpath", $W,
    "--collect-all", "poorsdr", "--collect-all", "poorsdr_win", "--copy-metadata", "poorsdr4all",
    "--collect-all", "pyaudiowpatch",
    "--collect-submodules", "websockets", "--collect-submodules", "uvicorn", "--collect-submodules", "fastapi",
    "--collect-all", "aiortc", "--exclude-module", "av", "--collect-all", "aioice", "--collect-all", "pylibsrtp", "--collect-submodules", "OpenSSL",
    "--add-data", "$paquete\viewers\*.py;poorsdr\viewers",
    "--add-data", "$I\src\poorsdr_win\recursos;poorsdr_win\recursos",
    "--hidden-import", "matplotlib.backends.backend_tkagg", "--hidden-import", "serial.tools.list_ports",
    "$I\src\launch_poorsdr.py")
foreach ($m in $ocultos) { $piargs = $piargs[0..($piargs.Count - 2)] + @("--hidden-import", $m) + $piargs[-1] }
X $Py -m PyInstaller @piargs
$exe = "$W\dist\PoorSDR4All\PoorSDR4All.exe"
if (-not (Test-Path $exe)) { throw "PyInstaller no generó PoorSDR4All.exe" }
# PyAV trae FFmpeg (con códecs GPL en sus ruedas): no puede ir dentro del ejecutable, lo descarga el instalador.
$interno = "$W\dist\PoorSDR4All\_internal"
foreach ($n in "av", "av.libs") { if (Test-Path "$interno\$n") { throw "PyAV/FFmpeg ha entrado en el paquete ($n): debe descargarlo el instalador (licencia de FFmpeg)." } }
if (Get-ChildItem $interno -Directory -Filter "av-*.dist-info" -ErrorAction SilentlyContinue) { throw "Metadatos de PyAV dentro del paquete: debe descargarlo el instalador." }
# El asistente ejecuta estos scripts dentro de WSL: sin ellos la instalación de OpenWebRX+ falla.
foreach ($f in "usuario.sh", "instalar.sh") {
    if (-not (Test-Path "$W\dist\PoorSDR4All\_internal\poorsdr_win\recursos\$f")) { throw "Falta $f en el paquete (poorsdr_win\recursos)" }
}
# Comprobación DENTRO del ejecutable: los módulos estándar que usan los complementos deben poder importarse
# (el libro de guardia falló una vez por faltar sqlite3). Los exclusivos de Linux/macOS se ignoran.
@'
import importlib, sys
posix = {"fcntl", "termios", "pwd", "grp", "resource", "readline", "curses", "syslog", "posix", "tty", "pty", "crypt", "nis", "spwd", "ossaudiodev", "_curses"}
fallan = []
for nombre in open(sys.argv[1], encoding="utf-8").read().split():
    raiz = nombre.split(".")[0]
    if raiz in posix or raiz not in sys.stdlib_module_names:
        continue
    try:
        importlib.import_module(nombre)
    except Exception as e:
        fallan.append(nombre + ": " + type(e).__name__)
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(fallan))
'@ | Set-Content "$W\comprobar_modulos.py" -Encoding UTF8
$ocultos | Set-Content "$W\modulos.txt" -Encoding UTF8
Remove-Item "$W\modulos_fallan.txt" -ErrorAction SilentlyContinue
Start-Process $exe -ArgumentList "`"$W\comprobar_modulos.py`" `"$W\modulos.txt`" `"$W\modulos_fallan.txt`"" -Wait
if (-not (Test-Path "$W\modulos_fallan.txt")) { throw "La comprobación de módulos no se ejecutó dentro del ejecutable" }
$fallan = (Get-Content "$W\modulos_fallan.txt" -Raw)
if ($fallan -and $fallan.Trim()) { throw "Faltan módulos en el ejecutable (los usan los complementos): $($fallan.Trim() -replace "`r?`n", ', ')" }
"Módulos de los complementos: todos importables dentro del ejecutable."
"PoorSDR4All.exe: {0:N1} MB; carpeta: {1:N0} MB" -f ((Get-Item $exe).Length / 1MB), ((Get-ChildItem "$W\dist\PoorSDR4All" -Recurse | Measure-Object Length -Sum).Sum / 1MB)
if (Test-Path "$W\pyi\PoorSDR4All\warn-PoorSDR4All.txt") { Subir "warn-PoorSDR4All.txt" "$W\pyi\PoorSDR4All\warn-PoorSDR4All.txt" }

Paso "Inno Setup"
$ISCC = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (!$ISCC) {
    $f = "$W\innosetup.exe"
    Invoke-WebRequest "https://jrsoftware.org/download.php/is.exe" -OutFile $f -UseBasicParsing
    $firma = Get-AuthenticodeSignature $f
    "Firma de Inno Setup: $($firma.Status) · $($firma.SignerCertificate.Subject)"
    if ($firma.Status -ne "Valid") { throw "La firma de Inno Setup no es válida; no lo instalo." }
    $p = Start-Process $f -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS" -Wait -PassThru
    $ISCC = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (!$ISCC) { throw "Inno Setup no se instaló" }
}
"ISCC: $ISCC"

Paso "Compilando el instalador"
# Inno necesita UTF-8 con BOM para leer los acentos del guion.
$iss = Get-Content "$I\inno\poorsdr4all.iss" -Raw -Encoding UTF8
[IO.File]::WriteAllText("$W\poorsdr4all.iss", $iss, [Text.UTF8Encoding]::new($true))
if (Test-Path "$W\out") { Remove-Item "$W\out" -Recurse -Force }
$defs = @("/DAppVersion=$V", "/DDistDir=$W\dist\PoorSDR4All", "/DPayloadDir=$P", "/DToolsDir=$I\inno", "/DAddonsDir=$A",
          "/DLicenseFile=$R\LICENSE", "/DIconFile=$W\poorsdr.ico", "/DOutDir=$W\out")
X $ISCC /Q @defs "$W\poorsdr4all.iss"
$setup = Get-ChildItem "$W\out\*.exe" | Select-Object -First 1
"Instalador: $($setup.Name) · {0:N1} MB" -f ($setup.Length / 1MB)

Paso "Subiendo al anfitrión"
Subir $setup.Name $setup.FullName
"Hecho."
