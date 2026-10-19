# Agente del laboratorio (VM de Windows). Se instala UNA vez y arranca al iniciar sesión el usuario.
# Corre con el usuario de la sesión (con privilegios elevados) para que WSL, los accesos directos y
# las ventanas sean los suyos. Vigila el servidor temporal del PC anfitrión y ejecuta las tareas que le manda.
param([switch]$Instalar)

$anfitrion = "http://192.168.122.1:8099"
$raiz = "C:\lab"
$ProgressPreference = "SilentlyContinue"

if ($Instalar) {
    New-Item -ItemType Directory -Force $raiz | Out-Null
    if ($PSCommandPath -ne "$raiz\lab-agente.ps1") { Copy-Item $PSCommandPath "$raiz\lab-agente.ps1" -Force }
    $usuario = "$env:COMPUTERNAME\$env:USERNAME"
    $accion = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $raiz\lab-agente.ps1"
    $disparador = New-ScheduledTaskTrigger -AtLogOn -User $usuario
    $principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Highest
    $ajustes = New-ScheduledTaskSettingsSet -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "LabAgente" -Action $accion -Trigger $disparador -Principal $principal -Settings $ajustes -Force | Out-Null
    Start-ScheduledTask -TaskName "LabAgente"
    Write-Host "Agente del laboratorio instalado para $usuario."
    exit
}

function Subir($nombre, $ruta) {
    try { Invoke-WebRequest -Uri "$anfitrion/subir/$nombre" -Method Put -InFile $ruta -UseBasicParsing -TimeoutSec 600 | Out-Null } catch {}
}

$ultima = ""
while ($true) {
    $orden = $null
    try { $orden = (Invoke-WebRequest -Uri "$anfitrion/orden-lab.txt" -UseBasicParsing -TimeoutSec 5).Content.Trim() } catch {}
    if ($orden -and $orden -ne $ultima) {
        $ultima = $orden
        $salida = "$raiz\salida.txt"
        try {
            New-Item -ItemType Directory -Force $raiz | Out-Null
            Invoke-WebRequest -Uri "$anfitrion/tarea.ps1" -OutFile "$raiz\tarea.ps1" -UseBasicParsing
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$raiz\tarea.ps1" *> $salida
            "`n[codigo de salida: $LASTEXITCODE]" | Add-Content $salida -Encoding UTF8
        } catch {
            ("ERROR DEL AGENTE: " + ($_ | Out-String)) | Add-Content $salida -Encoding UTF8
        }
        # El resultado lleva el id de su orden: el anfitrión espera SOLO el de la suya (nunca el de una tarea anterior).
        Subir "resultado-$orden.txt" $salida
    }
    Start-Sleep -Seconds 3
}
