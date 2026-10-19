# Prepara Windows para WSL2 (necesita administrador). Lo ejecuta el instalador de PoorSDR4All.
#   -Usbipd   instala además usbipd-win (pasar un SDR USB a WSL)
# Códigos de salida: 0 = listo · 10 = listo, pero Windows necesita REINICIAR · 20 = Windows demasiado antiguo · 1 = error
param([switch]$Usbipd)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$carpeta = Join-Path $env:ProgramData "PoorSDR4All"
New-Item -ItemType Directory -Force $carpeta | Out-Null
$registro = Join-Path $carpeta "preparar-wsl.log"
function Log($t) { "{0:HH:mm:ss} {1}" -f (Get-Date), $t | Tee-Object -FilePath $registro -Append }

function Nativo {  # ejecuta un programa nativo sin que un código distinto de 0 aborte el script
    $ErrorActionPreference = "Continue"
    $c, $r = $args
    $r = @($r)   # con un solo argumento, PowerShell lo trocearía letra a letra al expandirlo
    try { $o = & $c @r 2>&1; @{ ok = ($LASTEXITCODE -eq 0); out = ((($o | ForEach-Object { "$_" }) -join "`n") -replace "`0", "").Trim() } }
    catch { @{ ok = $false; out = "$_" } }
}

function UltimoMsi($repo, $patron) {
    # Sin la API de GitHub (limitada sin cuenta): se sigue la redirección de /releases/latest.
    $r = Invoke-WebRequest "https://github.com/$repo/releases/latest" -UseBasicParsing
    $u = if ($r.BaseResponse.ResponseUri) { $r.BaseResponse.ResponseUri.AbsoluteUri } else { $r.BaseResponse.RequestMessage.RequestUri.AbsoluteUri }
    $tag = $u.TrimEnd("/").Split("/")[-1]
    $h = (Invoke-WebRequest "https://github.com/$repo/releases/expanded_assets/$tag" -UseBasicParsing).Content
    $m = [regex]::Match($h, "href=""(/$repo/releases/download/[^""]*$patron)""")
    if (!$m.Success) { throw "No encuentro el instalador de $repo ($tag)" }
    "https://github.com$($m.Groups[1].Value)"
}

function InstalarMsi($url, $nombre, $firmante) {
    $f = Join-Path $env:TEMP $nombre
    Log "Descargando $url"
    Invoke-WebRequest $url -OutFile $f -UseBasicParsing
    $firma = Get-AuthenticodeSignature $f
    if ($firma.Status -ne "Valid" -or $firma.SignerCertificate.Subject -notmatch $firmante) {
        Remove-Item $f -Force
        throw "La firma digital de $nombre no es la esperada ($($firma.Status)); no lo instalo."
    }
    Log "Firma verificada: $($firma.SignerCertificate.Subject)"
    $p = Start-Process msiexec.exe -ArgumentList "/i `"$f`" /qn /norestart" -Wait -PassThru
    Remove-Item $f -Force -ErrorAction SilentlyContinue
    if ($p.ExitCode -notin 0, 3010) { throw "msiexec devolvió $($p.ExitCode) instalando $nombre" }
    return ($p.ExitCode -eq 3010)
}

try {
    Log "=== Preparando WSL ==="
    $build = [Environment]::OSVersion.Version.Build
    Log "Windows build $build"
    if ($build -lt 19041) { Log "Se necesita Windows 10 versión 2004 (build 19041) o posterior."; exit 20 }

    $reiniciar = $false

    # 1) Paquete de WSL (sin Microsoft Store: funciona también en Windows LTSC / sin Store)
    if (-not (Nativo wsl.exe --version).ok) {
        Log "Instalando WSL desde GitHub..."
        try { $url = UltimoMsi "microsoft/WSL" "\.x64\.msi" } catch { Log "No pude consultar GitHub: $_"; throw }
        if (InstalarMsi $url "wsl.msi" "Microsoft") { $reiniciar = $true }
    } else { Log "WSL ya instalado." }

    # 2) Componentes de Windows necesarios
    foreach ($f in "Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform") {
        $e = Get-WindowsOptionalFeature -Online -FeatureName $f
        if ($e.State -eq "Enabled") { Log "$f ya activo"; continue }
        if ($e.State -eq "EnablePending") { Log "$f pendiente de reinicio"; $reiniciar = $true; continue }
        Log "Activando $f..."
        $r = Enable-WindowsOptionalFeature -Online -FeatureName $f -All -NoRestart
        if ($r.RestartNeeded) { $reiniciar = $true }
    }
    Nativo wsl.exe --set-default-version 2 | Out-Null

    # 3) SDR por USB (opcional)
    if ($Usbipd) {
        if (Test-Path "$env:ProgramFiles\usbipd-win\usbipd.exe") { Log "usbipd-win ya instalado." }
        else {
            Log "Instalando usbipd-win..."
            $url = UltimoMsi "dorssel/usbipd-win" "x64\.msi"
            if (InstalarMsi $url "usbipd.msi" ".") { $reiniciar = $reiniciar }
        }
        # Autorizar de una vez los SDR habituales (este script corre como administrador): después un usuario
        # normal puede conectarlos a WSL sin permisos. Son directivas AutoBind de usbipd, una por VID:PID.
        $lista = Join-Path $PSScriptRoot "sdr-ids.txt"
        $usb = "$env:ProgramFiles\usbipd-win\usbipd.exe"
        if ((Test-Path $lista) -and (Test-Path $usb)) {
            $existentes = (Nativo $usb policy list).out   # usbipd escribe sus avisos por stderr: Nativo lo tolera
            $anadidas = 0
            $todos = @()
            foreach ($l in Get-Content $lista) {
                $id = ($l -split "#")[0].Trim()
                if ($id -notmatch '^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$') { continue }
                $todos += $id.ToLower()
                if ($existentes -match [regex]::Escape($id)) { continue }
                if ((Nativo $usb policy add --effect Allow --operation AutoBind --hardware-id $id).ok) { $anadidas++ }
            }
            Log "Directivas de usbipd (SDR autorizados): $anadidas nuevas"
            # AutoBind actúa cuando se ENCHUFA el dispositivo: los SDR que ya estén conectados ahora se enlazan aquí.
            try { $dispositivos = ((Nativo $usb state).out | ConvertFrom-Json).Devices } catch { $dispositivos = @() }
            $enlazados = 0
            foreach ($d in $dispositivos) {
                if ($d.PersistedGuid -or ("$($d.InstanceId)" -notmatch 'VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})')) { continue }
                if ($todos -contains ("$($Matches[1]):$($Matches[2])").ToLower()) { if ((Nativo $usb bind --busid $d.BusId).ok) { $enlazados++ } }
            }
            Log "SDR ya conectados y enlazados: $enlazados"
        }
    }

    if ($reiniciar) { Log "Hace falta reiniciar Windows."; exit 10 }
    Log "WSL preparado."
    exit 0
}
catch {
    Log "ERROR: $_"
    exit 1
}
