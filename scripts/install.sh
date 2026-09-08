#!/usr/bin/env bash
#
# Instalador de PoorSDR4 + OpenWebRX+ nativo.
#
# OpenWebRX+ y sus dependencias NO se distribuyen con este proyecto: este script
# clona el codigo fuente oficial en revisiones FIJADAS y lo compila en el equipo
# de destino. El resultado permanece en la maquina del usuario.
#
#   Fuentes fijadas (GitHub):
#     luarvique/csdr            0.18.37 @ c5d4224461267d67b1629821b179f95378477956
#     luarvique/pycsdr          0.18.37 @ db2050bd02ddd1d630cee8d27aaa4432767717ca
#     luarvique/owrx_connector  0.6.5  @ 870285269143048f850151346980942a12ccf24b
#     luarvique/openwebrx       1.2.119 @ 55dae2e6d798e133e8ac25769a3d2a1ea4d27419
#     Acuantico/owrx-spider     7741d530a18a3f5aae08a2e3435fc6ed1d1f6126  (plugin de spots, opcional)
#
# Uso:
#   ./install.sh
#
# Variables de entorno:
#   SKIP_OWRX_BUILD=1     No compilar/instalar OpenWebRX+ (solo dependencias de PoorSDR)
#   SKIP_SPIDER=1         No instalar el plugin/servicio de spots (spiderd)
#   INSTALL_WEB_EXTRAS=0  Por defecto se instalan los extras del servidor web
#                        remoto (FastAPI, aiortc/WebRTC...) para poder usar el
#                        panel web sin pasos aparte. Pon esta variable a 0 para
#                        omitirlos (solo consola de escritorio, sin servidor web).
#   RESET_OWRX_CONFIG=1   Reemplazar configuración OWRX (crea copia de seguridad)
#   OWRX_BUILD_JOBS=N     Hilos de compilacion (por defecto: nproc)
#   OWRX_BUILD_ROOT=DIR   Carpeta de compilacion (por defecto: runtime/owrx-native-build)
#   PIN_CSDR / PIN_PYCSDR / PIN_OWRX_CONNECTOR / PIN_OPENWEBRX / PIN_OWRX_SPIDER
#                        Sobrescribir las revisiones fijadas
#   INSTALL_7LED_FONT=0  Por defecto se descarga la fuente "7LED" (dafont.com,
#                        "gratis para uso personal") directo desde su fuente
#                        oficial y se instala para el usuario que ejecuta el
#                        instalador — NUNCA se distribuye una copia con este
#                        proyecto (el .ttf no está en el repositorio; se
#                        descarga en el momento, en cada máquina, igual que
#                        OpenWebRX+/csdr se clonan de GitHub). Pon esta
#                        variable a 0 para omitirlo (sin red, o si se prefiere
#                        no descargar nada de terceros); en ese caso, o si la
#                        descarga falla por cualquier motivo, la consola usa
#                        DSEG7 Classic (SIL OFL 1.1, sí redistribuible), que
#                        se instala sola de todos modos.
#
set -euo pipefail

# scripts/ vive en la raíz del repo; los recursos del runtime heredado siguen en
# src/poorsdr/_vendor: DSP y protocolo de bajo nivel envueltos por poorsdr/services/.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${PROJECT_DIR}/src/poorsdr/_vendor"
RUNTIME_DIR="${VENDOR_DIR}/runtime"
PATCH_DIR="${PROJECT_DIR}/patches"
BUILD_ROOT="${OWRX_BUILD_ROOT:-${RUNTIME_DIR}/owrx-native-build}"
JOBS="${OWRX_BUILD_JOBS:-$(nproc 2>/dev/null || echo 2)}"

SKIP_OWRX_BUILD="${SKIP_OWRX_BUILD:-0}"
SKIP_SPIDER="${SKIP_SPIDER:-0}"
INSTALL_WEB_EXTRAS="${INSTALL_WEB_EXTRAS:-1}"
RESET_OWRX_CONFIG="${RESET_OWRX_CONFIG:-0}"
INSTALL_7LED_FONT="${INSTALL_7LED_FONT:-1}"

PIN_CSDR="${PIN_CSDR:-c5d4224461267d67b1629821b179f95378477956}"
PIN_PYCSDR="${PIN_PYCSDR:-db2050bd02ddd1d630cee8d27aaa4432767717ca}"
PIN_OWRX_CONNECTOR="${PIN_OWRX_CONNECTOR:-870285269143048f850151346980942a12ccf24b}"
PIN_OPENWEBRX="${PIN_OPENWEBRX:-55dae2e6d798e133e8ac25769a3d2a1ea4d27419}"
PIN_OWRX_SPIDER="${PIN_OWRX_SPIDER:-7741d530a18a3f5aae08a2e3435fc6ed1d1f6126}"

OWRX_PORT=8073
OS_FAMILY=""

log()  { echo "==> $*"; }
info() { echo "    $*"; }
warn() { echo "AVISO: $*" >&2; }
die()  { echo "ERROR: $*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

# --------------------------------------------------------------------------- #
# Deteccion del sistema
# --------------------------------------------------------------------------- #
detect_os() {
  [[ -r /etc/os-release ]] || die "No se pudo leer /etc/os-release; sistema no soportado."
  # shellcheck disable=SC1091
  . /etc/os-release
  local id="${ID:-}" like="${ID_LIKE:-}"
  if [[ "$id" == "arch" || "$like" == *arch* ]]; then
    OS_FAMILY="arch"
  elif [[ "$id" == "debian" || "$id" == "ubuntu" || "$like" == *debian* ]]; then
    OS_FAMILY="debian"
  else
    die "Distribucion no soportada automaticamente (ID='${id}' ID_LIKE='${like}').
Instala manualmente: toolchain de C/C++ + cmake, libfftw3, libsamplerate,
librtlsdr, SoapySDR, Python3 + tk + PyGObject/Gtk3 + cairo, ffmpeg, hamlib,
y luego compila csdr/pycsdr/owrx_connector/openwebrx desde sus fuentes fijadas."
  fi
  log "Sistema detectado: ${PRETTY_NAME:-$id}  (familia: ${OS_FAMILY})"
  need_cmd sudo || die "Se necesita 'sudo'."
  need_cmd git  || die "Se necesita 'git'."
}

# --------------------------------------------------------------------------- #
# Fuentes: clonar en revision fijada
# --------------------------------------------------------------------------- #
clone_ref() {
  local url="$1" ref="$2" dst="$3"
  if [[ ! -d "${dst}/.git" ]]; then
    git clone "${url}" "${dst}"
  fi
  [[ "$(git -C "${dst}" remote get-url origin)" == "${url}" ]] \
    || die "Origen inesperado en ${dst} (esperado ${url})"
  git -C "${dst}" fetch --tags --force origin
  git -C "${dst}" checkout --detach "${ref}"
  git -C "${dst}" submodule update --init --recursive || true
}

apply_upstream_patch() {
  local src="$1" patch="$2"
  [[ -f "${patch}" ]] || die "No se encontró el parche requerido: ${patch}"
  if git -C "${src}" apply --check "${patch}"; then
    git -C "${src}" apply "${patch}"
  elif git -C "${src}" apply --reverse --check "${patch}"; then
    info "Parche ya aplicado: $(basename "${patch}")"
  else
    die "El parche no aplica limpiamente sobre la revisión fijada: ${patch}"
  fi
}

# --------------------------------------------------------------------------- #
# Dependencias del sistema
# --------------------------------------------------------------------------- #
pacman_install() {
  # Instala los paquetes disponibles; informa (sin abortar) de los que no
  # existan. Si la transacción conjunta falla (típicamente un conflicto de
  # dependencias entre paquetes ya instalados y una version mas nueva del
  # repo oficial, p. ej. un ffmpeg que rompe mpv/chromaprint en un sistema
  # parcialmente actualizado) NO se aborta el script entero: se reintenta
  # paquete a paquete para que un solo conflicto no bloquee el resto.
  local want=("$@") have=() miss=() pkg
  for pkg in "${want[@]}"; do
    if pacman -Si "${pkg}" >/dev/null 2>&1 || pacman -Sg "${pkg}" >/dev/null 2>&1; then
      have+=("${pkg}")
    else
      miss+=("${pkg}")
    fi
  done

  if [[ ${#have[@]} -gt 0 ]] && ! sudo pacman -S --needed --noconfirm "${have[@]}"; then
    warn "La instalación conjunta de paquetes falló (probablemente un conflicto de dependencias)."
    warn "Reintentando paquete a paquete para no bloquear el resto de la instalación..."
    local failed=()
    for pkg in "${have[@]}"; do
      sudo pacman -S --needed --noconfirm "${pkg}" || failed+=("${pkg}")
    done
    if [[ ${#failed[@]} -gt 0 ]]; then
      warn "No se pudieron instalar (revisa el conflicto; suele bastar 'sudo pacman -Syu' antes de reintentar): ${failed[*]}"
    fi
  fi

  if [[ ${#miss[@]} -gt 0 ]]; then
    warn "Paquetes no encontrados en los repos oficiales (se omiten): ${miss[*]}"
    info "Para modos digitales avanzados quiza necesites algunos via AUR."
  fi
}

pacman_install_optional() {
  # Instala uno a uno; un fallo (conflicto, no disponible) no aborta el script.
  local pkg
  for pkg in "$@"; do
    if pacman -Si "${pkg}" >/dev/null 2>&1; then
      sudo pacman -S --needed --noconfirm "${pkg}" \
        || warn "No se pudo instalar '${pkg}' (se continua)."
    else
      warn "Paquete opcional no encontrado: ${pkg}"
    fi
  done
}

ensure_rtlsdr_arch() {
  # No forzar 'rtl-sdr': entra en conflicto con 'rtl-sdr-blog' (fork RTL-SDR Blog),
  # que ya provee librtlsdr. Solo instalar si no hay ningun proveedor.
  if compgen -G "/usr/lib/librtlsdr.so*" >/dev/null 2>&1 \
     || pacman -Qq rtl-sdr rtl-sdr-blog >/dev/null 2>&1; then
    info "librtlsdr ya presente ($(pacman -Qq rtl-sdr rtl-sdr-blog 2>/dev/null | tr '\n' ' ')): no se toca."
  else
    pacman_install_optional rtl-sdr
  fi
}

refresh_mirrors_arch() {
  # Confirmado en real: un -Syu de cientos de paquetes (un sistema con tiempo
  # sin actualizar no es raro) puede fallar entero porque UN mirror de la
  # mirrorlist esta caido o lentisimo ("Operation too slow. Less than 1
  # bytes/sec", timeouts) — nada que ver con conflictos de paquetes. Antes de
  # intentar sincronizar, reordenar la mirrorlist por velocidad real evita
  # que ese mirror muerto bloquee todo el instalador. reflector es un
  # paquete pequeño y autocontenido (sin dependencias de peso sobre el resto
  # del sistema): instalarlo suelto, sin sincronizar antes, no conlleva el
  # riesgo de actualizacion parcial que sí tiene el -Syu grande de abajo.
  if ! command -v reflector >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm reflector 2>/dev/null || true
  fi
  if command -v reflector >/dev/null 2>&1; then
    log "Reordenando mirrors por velocidad real (reflector, máx. 60s)..."
    # --sort rate mide la velocidad real descargando de cada mirror
    # candidato, uno a uno, sin imprimir nada mientras tanto: sin acotar la
    # lista candidata (--latest/--number) esto puede tardar varios minutos
    # en silencio, dando la sensación de que el instalador se ha colgado.
    # timeout 60 asegura que este paso nunca bloquea el instalador: si no
    # termina a tiempo, se sigue con la mirrorlist que ya hubiera.
    sudo timeout 60 reflector --latest 20 --number 10 --sort rate --protocol https \
      --save /etc/pacman.d/mirrorlist 2>/dev/null \
      || warn "reflector no terminó a tiempo (60s) o falló; se sigue con la mirrorlist actual."
  else
    warn "reflector no disponible; se sigue con la mirrorlist actual (puede haber mirrors lentos)."
  fi
}

sync_system_arch() {
  # Instalar paquetes nuevos sin haber sincronizado antes el sistema completo
  # es una "actualizacion parcial": Arch no la soporta porque puede traer una
  # libreria (glibc, openssl...) mas nueva que el resto del sistema instalado,
  # dejando binarios y bibliotecas con versiones incompatibles entre si. Es
  # la causa mas comun de que un sistema Arch quede inutilizable tras
  # instalar un paquete cualquiera. Por eso el sistema se sincroniza entero
  # (pacman -Syu) antes de tocar nada especifico de PoorSDR.
  refresh_mirrors_arch
  log "Sincronizando el sistema completo (pacman -Syu) antes de instalar nada..."
  local attempt
  for attempt in 1 2 3; do
    if sudo pacman -Syu --noconfirm; then
      return 0
    fi
    warn "pacman -Syu fallo (intento ${attempt}/3)."
    if [[ "${attempt}" == "1" ]]; then
      sudo pacman -Sy --noconfirm archlinux-keyring 2>/dev/null || true
    fi
    if [[ "${attempt}" -lt 3 ]]; then
      info "Puede ser un fallo de red/mirror pasajero; reintentando en 5s..."
      sleep 5
    fi
  done
  die "No se pudo sincronizar el sistema (pacman -Syu) tras 3 intentos. Suele ser un problema de mirrors, no de conflictos: prueba 'sudo reflector --sort rate --save /etc/pacman.d/mirrorlist' (o 'rate-mirrors' si lo tienes) a mano y reintenta el instalador. Resuelvelo antes de continuar: instalar paquetes nuevos sin el sistema sincronizado puede dejar Arch en un estado roto (actualizacion parcial)."
}

install_system_deps_arch() {
  sync_system_arch
  log "Instalando dependencias del sistema (Arch)..."
  local base=(
    base-devel git cmake pkgconf rsync curl fontconfig
    soapysdr fftw libsamplerate libusb codec2
    ffmpeg hamlib speexdsp portaudio libpulse libsndfile
    tk gtk3 python-gobject python-cairo gobject-introspection cairo pango
    python python-pip
    python-numpy python-pillow python-psutil python-pyserial python-pyaudio
    python-pynput python-matplotlib python-cryptography python-setuptools
  )
  pacman_install "${base[@]}"
  # librtlsdr: respetar rtl-sdr-blog si ya esta instalado (evita conflicto).
  ensure_rtlsdr_arch
  # Opcionales: no abortan si faltan o entran en conflicto.
  pacman_install_optional soapyrtlsdr direwolf multimon-ng lame
  install_digital_decoders_arch
}

install_digital_decoders_arch() {
  # OpenWebRX+ decodifica FT8/FT4/JT65/WSPR con el binario 'jt9' de WSJT-X, JS8
  # con js8call y WSPR con wsprd. Sin ellos el panel Digi no ofrece esos modos.
  log "Instalando decodificadores digitales (WSJT-X / JS8Call)..."

  # IMPORTANTE: los forks 'wsjtx-improved-*' (chaotic-aur) traen un 'jt9' con un
  # layout de memoria compartida distinto y OpenWebRX+ lo hace CRASHEAR
  # (SIGSEGV / return code -11). Hay que usar el WSJT-X OFICIAL (repo extra).
  if pacman -Qq | grep -qE '^wsjtx-improved'; then
    warn "Detectado wsjtx-improved: su 'jt9' es incompatible con OpenWebRX+ (crashea)."
    info "  Reemplazalo por el oficial:  sudo pacman -Rns \$(pacman -Qq|grep '^wsjtx-improved') && sudo pacman -S extra/wsjtx"
  fi

  local aur=""
  for h in paru yay pikaur; do command -v "$h" >/dev/null 2>&1 && { aur="$h"; break; }; done

  # Si hay un fork 'improved' instalado, su jt9 CRASHEA OpenWebRX+: retirarlo.
  local imp
  imp="$(pacman -Qq 2>/dev/null | grep '^wsjtx-improved' || true)"
  if [[ -n "$imp" ]]; then
    warn "Retirando fork incompatible: ${imp}"
    sudo pacman -Rns --noconfirm ${imp} || warn "No se pudo retirar ${imp}; hazlo a mano."
    sudo rm -f /usr/local/bin/jt9 /usr/local/bin/wsprd
  fi

  local pkg
  for pkg in wsjtx js8call; do
    if pacman -Qq "$pkg" >/dev/null 2>&1 \
       && ! pacman -Qi "$pkg" 2>/dev/null | grep -qi improved; then
      info "${pkg} ya instalado."
      continue
    fi
    if pacman -Si "extra/${pkg}" >/dev/null 2>&1; then
      sudo pacman -S --needed --noconfirm "extra/${pkg}" || warn "No se pudo instalar extra/${pkg}."
    elif [[ -n "$aur" ]]; then
      # 'aur/<pkg>' fuerza el paquete oficial y salta los 'provides' de terceros.
      info "Instalando ${pkg} oficial desde AUR (${aur})..."
      "$aur" -S --needed --noconfirm "aur/${pkg}" \
        || "$aur" -S --needed --noconfirm "$pkg" \
        || warn "AUR: no se pudo instalar '${pkg}'."
    else
      warn "Falta '${pkg}' y no hay ayudante de AUR. Para FT8/FT4/JS8:"
      info "  paru -S aur/${pkg}     (el OFICIAL, NO 'wsjtx-improved')"
    fi
  done

  # wsjtx-improved (chaotic-aur) instala jt9/wsprd en /usr/lib/wsjtx, fuera del
  # PATH: OpenWebRX+ no los ve. Enlazarlos a /usr/local/bin (sí en el PATH systemd).
  local b
  for b in jt9 wsprd jt65 ft8code jt65code jt9code; do
    if ! command -v "$b" >/dev/null 2>&1; then
      for d in /usr/lib/wsjtx /usr/lib/wsjtx-improved /opt/wsjtx/bin; do
        if [[ -x "${d}/${b}" ]]; then
          sudo ln -sf "${d}/${b}" "/usr/local/bin/${b}"
          info "enlazado ${d}/${b} -> /usr/local/bin/${b}"
          break
        fi
      done
    fi
  done

  if command -v jt9 >/dev/null 2>&1; then
    info "jt9 disponible: OpenWebRX+ podra decodificar FT8/FT4."
    if systemctl is-active --quiet openwebrx.service 2>/dev/null; then
      sudo -n systemctl restart openwebrx.service 2>/dev/null \
        || sudo systemctl restart openwebrx.service 2>/dev/null || true
    fi
  else
    warn "No se encontro 'jt9' (WSJT-X): el panel Digi no mostrara FT8/FT4/JT65."
  fi
}

install_system_deps_debian() {
  log "Instalando dependencias del sistema (Debian/Ubuntu)..."
  local packages=(
    python3 python3-venv python3-tk python3-pip python3-gi python3-cairo gir1.2-gtk-3.0
    python3-numpy python3-serial python3-pil python3-psutil python3-pynput python3-pyaudio
    python3-matplotlib python3-cryptography python3-setuptools python3-all-dev
    python3-requests python3-yaml python3-dateutil
    ffmpeg libhamlib-utils libspeexdsp1 portaudio19-dev pulseaudio-utils
    git ca-certificates build-essential devscripts debhelper fakeroot dh-python
    cmake pkg-config rsync curl fontconfig
    libfftw3-dev libsamplerate0-dev librtlsdr-dev libsoapysdr-dev
    libcodec2-dev libhamlib-dev libpulse-dev libsndfile1-dev libspeexdsp-dev
    soapysdr-tools rtl-sdr
  )
  local optional=( wsjtx direwolf multimon-ng lame )
  sudo dpkg --configure -a || true
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${optional[@]}" || \
    warn "Algunos paquetes opcionales no se instalaron."
}

install_system_deps() {
  case "${OS_FAMILY}" in
    arch)   install_system_deps_arch ;;
    debian) install_system_deps_debian ;;
  esac
}

# --------------------------------------------------------------------------- #
# Decodificador FFT nativo de PoorSDR
# --------------------------------------------------------------------------- #
build_fft_so() {
  log "Compilando el acelerador FFT/ADPCM opcional..."
  python3 "${PROJECT_DIR}/scripts/build_native.py"
}

# --------------------------------------------------------------------------- #
# OpenWebRX+ nativo
# --------------------------------------------------------------------------- #
# pycsdr y OpenWebRX+ se instalan en este venv dedicado, nunca sobre el
# Python del sistema: un "pip install" como root ahi (con --break-system-packages)
# puede pisar los mismos paquetes que pacman ya gestiona (python-cryptography,
# python-numpy, python-setuptools...), dejando la base de datos de pacman sin
# saber que hay realmente instalado — una fuente de roturas dificiles de
# diagnosticar y, en el peor caso, de que herramientas del sistema que
# dependen de esas mismas librerias dejen de funcionar.
OWRX_VENV="/opt/poorsdr4-owrx/venv"

ensure_owrx_venv() {
  if [[ ! -x "${OWRX_VENV}/bin/python" ]]; then
    log "Creando entorno virtual dedicado para OpenWebRX+/pycsdr (${OWRX_VENV})..."
    sudo install -d -m 755 "$(dirname "${OWRX_VENV}")"
    sudo python3 -m venv "${OWRX_VENV}"
  fi
  # Confirmado en real: segun el umask de la sesion sudo, "python3 -m venv"
  # puede dejar el venv en 0700 (solo root) — inaccesible tanto para este
  # mismo script (que llama a su python sin sudo mas abajo) como para el
  # usuario de sistema "openwebrx" que luego arranca el servicio systemd
  # desde ahi. Forzar lectura/ejecucion para todos, sin tocar los permisos
  # de escritura (siguen siendo solo de root).
  sudo chmod -R a+rX "${OWRX_VENV}"
  # Confirmado en real: en Python 3.12+, "python3 -m venv" ya NO incluye
  # setuptools/wheel por defecto (antes venian de serie via ensurepip). Los
  # "pip install --no-build-isolation" de mas abajo (pycsdr) asumen que el
  # backend de build ya esta en el entorno destino, en vez de crear uno
  # aislado — sin setuptools, fallan con "Cannot import
  # 'setuptools.build_meta'" antes de intentar compilar nada.
  sudo "${OWRX_VENV}/bin/pip" install --quiet --upgrade pip setuptools wheel
}

cmake_build_install() {
  local src="$1"; shift
  # owrx_connector 0.6.5 declara cmake_minimum_required(VERSION 3.0); CMake >= 4
  # ya no acepta compat < 3.5. CMAKE_POLICY_VERSION_MINIMUM lo desbloquea.
  cmake -S "${src}" -B "${src}/build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DCMAKE_PREFIX_PATH=/usr/local -DCMAKE_INSTALL_PREFIX=/usr/local "$@"
  cmake --build "${src}/build" --parallel "${JOBS}"
  sudo cmake --install "${src}/build"
  # Confirmado en real: "cmake --install" puede dejar carpetas nuevas bajo
  # /usr/local (p. ej. lib/cmake/Csdr/) en 0700 segun el umask de la sesion
  # sudo — el siguiente paquete del stack (owrx_connector) configura con
  # cmake SIN sudo y necesita poder leerlas para encontrar el paquete
  # instalado (find_package); si no puede, falla con "no encontré
  # CsdrConfig.cmake" aunque el fichero exista. Igual que en
  # ensure_owrx_venv: solo lectura/ejecucion para todos, nunca escritura.
  sudo chmod -R a+rX /usr/local
}

owrx_pkg_dir() {
  # Imprime la ruta del paquete 'owrx' instalado (la que contiene 'controllers/'),
  # ignorando el directorio vacio 'owrx/' del repo (owrx es namespace package).
  # Se introspecciona con el python del venv de OpenWebRX+: ahi es donde
  # realmente esta instalado, no en el Python del sistema.
  "${OWRX_VENV}/bin/python" - <<'PY' 2>/dev/null || true
import os, owrx
for p in owrx.__path__:
    if os.path.isdir(os.path.join(p, "controllers")):
        print(os.path.abspath(p)); break
PY
}

ensure_local_ldconfig() {
  if [[ "${OS_FAMILY}" == "arch" && ! -e /etc/ld.so.conf.d/usr-local.conf ]]; then
    echo "/usr/local/lib" | sudo tee /etc/ld.so.conf.d/usr-local.conf >/dev/null
  fi
  sudo ldconfig
}

build_openwebrx_stack_arch() {
  mkdir -p "${BUILD_ROOT}"
  ensure_owrx_venv

  log "Compilando csdr ${PIN_CSDR}..."
  clone_ref https://github.com/luarvique/csdr.git "${PIN_CSDR}" "${BUILD_ROOT}/csdr"
  cmake_build_install "${BUILD_ROOT}/csdr"
  ensure_local_ldconfig

  log "Compilando owrx_connector ${PIN_OWRX_CONNECTOR}..."
  clone_ref https://github.com/luarvique/owrx_connector.git "${PIN_OWRX_CONNECTOR}" "${BUILD_ROOT}/owrx_connector"
  cmake_build_install "${BUILD_ROOT}/owrx_connector"
  ensure_local_ldconfig

  log "Compilando e instalando pycsdr ${PIN_PYCSDR}..."
  clone_ref https://github.com/luarvique/pycsdr.git "${PIN_PYCSDR}" "${BUILD_ROOT}/pycsdr"
  apply_upstream_patch "${BUILD_ROOT}/pycsdr" \
    "${PATCH_DIR}/pycsdr/0001-gcc15-pymoduledef-initializers.patch"
  ( cd "${BUILD_ROOT}/pycsdr" && \
    sudo env CPPFLAGS="-I/usr/local/include" LDFLAGS="-L/usr/local/lib" \
      "${OWRX_VENV}/bin/pip" install --no-build-isolation . )
  # Cada "pip install" con sudo dentro del venv puede volver a dejar lo que
  # instala en 0700 (mismo motivo que en ensure_owrx_venv/cmake_build_install
  # — el umask de la sesion sudo, no algo fijo de este venv), así que hay
  # que repetir el chmod después de cada uno, no solo al crear el venv.
  sudo chmod -R a+rX "${OWRX_VENV}"

  log "Instalando OpenWebRX+ ${PIN_OPENWEBRX}..."
  clone_ref https://github.com/luarvique/openwebrx.git "${PIN_OPENWEBRX}" "${BUILD_ROOT}/openwebrx"
  apply_upstream_patch "${BUILD_ROOT}/openwebrx" \
    "${PATCH_DIR}/openwebrx/0001-replace-pkg-resources.patch"
  ( cd "${BUILD_ROOT}/openwebrx" && sudo "${OWRX_VENV}/bin/pip" install --upgrade . )
  sudo chmod -R a+rX "${OWRX_VENV}"
  # Limpiar copias .bak-* que instalaciones previas del plugin de spots pudieran
  # haber dejado (pip acaba de reinstalar los ficheros originales).
  local owrx_pkg
  owrx_pkg="$(owrx_pkg_dir)"
  [[ -n "${owrx_pkg}" ]] && sudo find "${owrx_pkg}" -name '*.bak-*' -delete 2>/dev/null || true

  # Configuracion de sistema (equivalente a debian/openwebrx.install)
  sudo install -d /etc/openwebrx/openwebrx.conf.d /etc/openwebrx/markers.d
  local f
  for f in bands.json bands-r1.json bands-r2.json bands-r3.json openwebrx.conf; do
    [[ -f "${BUILD_ROOT}/openwebrx/${f}" ]] && \
      sudo install -m644 "${BUILD_ROOT}/openwebrx/${f}" /etc/openwebrx/
  done
  [[ -d "${BUILD_ROOT}/openwebrx/bookmarks.d" ]] && \
    sudo rsync -a "${BUILD_ROOT}/openwebrx/bookmarks.d/" /etc/openwebrx/bookmarks.d/

  # Unidad systemd: el ejecutable vive en el venv dedicado, no en el PATH del sistema.
  local owrx_bin="${OWRX_VENV}/bin/openwebrx"
  sudo install -d /etc/systemd/system
  sudo tee /etc/systemd/system/openwebrx.service >/dev/null <<EOF
[Unit]
Description=OpenWebRX+ WebSDR (PoorSDR4 nativo)
After=network.target

[Service]
Type=simple
User=openwebrx
Group=openwebrx
ExecStart=${owrx_bin}
Restart=always
RestartSec=5
Environment="HOME=/tmp"

[Install]
WantedBy=multi-user.target
EOF
}

build_openwebrx_stack_debian() {
  mkdir -p "${BUILD_ROOT}"
  build_deb() {
    local src="$1"
    log "Empaquetando $(basename "${src}")..."
    ( cd "${src}" && DEB_BUILD_OPTIONS=nocheck MAKEFLAGS="-j${JOBS}" dpkg-buildpackage -us -uc -b )
  }
  install_debs() {
    local parent="$1"; shift
    local files=() pat file
    for pat in "$@"; do
      while IFS= read -r file; do files+=("${file}"); done \
        < <(find "${parent}" -maxdepth 1 -type f -name "${pat}" -print)
    done
    [[ ${#files[@]} -gt 0 ]] || die "No se encontraron .deb en ${parent}"
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${files[@]}"
  }

  log "Compilando csdr ${PIN_CSDR}..."
  clone_ref https://github.com/luarvique/csdr.git "${PIN_CSDR}" "${BUILD_ROOT}/csdr"
  build_deb "${BUILD_ROOT}/csdr"
  install_debs "${BUILD_ROOT}" 'libcsdr0_*.deb' 'libcsdr-dev_*.deb' 'csdr_*.deb' 'nmux_*.deb'

  log "Compilando pycsdr ${PIN_PYCSDR}..."
  clone_ref https://github.com/luarvique/pycsdr.git "${PIN_PYCSDR}" "${BUILD_ROOT}/pycsdr"
  apply_upstream_patch "${BUILD_ROOT}/pycsdr" \
    "${PATCH_DIR}/pycsdr/0001-gcc15-pymoduledef-initializers.patch"
  build_deb "${BUILD_ROOT}/pycsdr"
  install_debs "${BUILD_ROOT}" 'python3-csdr_*.deb'

  log "Compilando owrx_connector ${PIN_OWRX_CONNECTOR}..."
  clone_ref https://github.com/luarvique/owrx_connector.git "${PIN_OWRX_CONNECTOR}" "${BUILD_ROOT}/owrx_connector"
  build_deb "${BUILD_ROOT}/owrx_connector"
  install_debs "${BUILD_ROOT}" 'libowrx-connector_*.deb' 'rtl-connector_*.deb' \
    'rtl-tcp-connector_*.deb' 'soapy-connector_*.deb' 'owrx-connector_*.deb'

  log "Compilando OpenWebRX+ ${PIN_OPENWEBRX}..."
  clone_ref https://github.com/luarvique/openwebrx.git "${PIN_OPENWEBRX}" "${BUILD_ROOT}/openwebrx"
  apply_upstream_patch "${BUILD_ROOT}/openwebrx" \
    "${PATCH_DIR}/openwebrx/0001-replace-pkg-resources.patch"
  build_deb "${BUILD_ROOT}/openwebrx"
  install_debs "${BUILD_ROOT}" 'openwebrx_*.deb'
}

setup_openwebrx_user() {
  log "Creando usuario de sistema 'openwebrx' y /var/lib/openwebrx..."
  python3 "${PROJECT_DIR}/scripts/check_owrx_config.py" \
    || die "La plantilla OpenWebRX+ no coincide con las bandas de PoorSDR4All."
  if ! getent group plugdev >/dev/null 2>&1; then
    sudo groupadd --system plugdev
  fi
  if ! getent passwd openwebrx >/dev/null 2>&1; then
    sudo useradd --system --user-group --no-create-home \
      --home-dir /var/lib/openwebrx --shell /usr/bin/nologin openwebrx
  fi
  # Grupos para acceso a SDR por USB y a puertos serie (uucp en Arch, dialout en Debian).
  local g
  for g in plugdev uucp dialout audio; do
    getent group "${g}" >/dev/null 2>&1 && sudo usermod -aG "${g}" openwebrx || true
  done
  # El usuario que ejecuta PoorSDR pertenece al grupo 'openwebrx' (para la regla polkit).
  sudo usermod -aG openwebrx "${USER}" || true

  sudo install -d -o openwebrx -g openwebrx /var/lib/openwebrx

  local backup_dir="/var/lib/openwebrx/backup-poorsdr-$(date -u +%Y%m%dT%H%M%SZ)"
  if [[ "${RESET_OWRX_CONFIG}" == "1" ]]; then
    sudo install -d -o openwebrx -g openwebrx -m 700 "${backup_dir}"
    local existing
    for existing in settings.json users.json bookmarks.json; do
      [[ ! -f "/var/lib/openwebrx/${existing}" ]] || \
        sudo cp -a "/var/lib/openwebrx/${existing}" "${backup_dir}/${existing}"
    done
    info "Configuración OWRX respaldada en ${backup_dir}."
  fi

  # La plantilla solo se instala en una configuración nueva o al solicitar un
  # reset explícito. Una actualización normal nunca pisa receptores ni cuentas.
  local tpl="${PROJECT_DIR}/assets/owrx/settings.json"
  if [[ -f "${tpl}" && ( ! -f /var/lib/openwebrx/settings.json || "${RESET_OWRX_CONFIG}" == "1" ) ]]; then
    sudo install -o openwebrx -g openwebrx -m 640 "${tpl}" /var/lib/openwebrx/settings.json
    info "settings.json instalado desde la plantilla (assets/owrx/settings.json)."
  else
    [[ -e /var/lib/openwebrx/settings.json ]] || \
      { echo '{}' | sudo tee /var/lib/openwebrx/settings.json >/dev/null; sudo chown openwebrx: /var/lib/openwebrx/settings.json; }
  fi
  # Usuarios: crear vacío únicamente si no existe o durante un reset explícito.
  if [[ ! -f /var/lib/openwebrx/users.json || "${RESET_OWRX_CONFIG}" == "1" ]]; then
    echo '[]' | sudo tee /var/lib/openwebrx/users.json >/dev/null
    sudo chown openwebrx: /var/lib/openwebrx/users.json
    sudo chmod 600 /var/lib/openwebrx/users.json
  fi

  # Bookmarks vacios: OpenWebRX+ genera por si mismo los marcadores de banda
  # (FT8/FT4/JS8/WSPR/CW/SSB...) segun los decodificadores instalados. Un
  # bookmarks.json propio duplicaria esos marcadores.
  if [[ ! -f /var/lib/openwebrx/bookmarks.json || "${RESET_OWRX_CONFIG}" == "1" ]]; then
    echo '[]' | sudo tee /var/lib/openwebrx/bookmarks.json >/dev/null
    sudo chown openwebrx: /var/lib/openwebrx/bookmarks.json
    sudo chmod 644 /var/lib/openwebrx/bookmarks.json
  fi
}

setup_openwebrx_polkit() {
  # Permite a PoorSDR arrancar/parar openwebrx.service sin pedir contrasena.
  log "Instalando regla polkit para gestionar openwebrx.service sin sudo..."
  sudo install -d /etc/polkit-1/rules.d
  sudo tee /etc/polkit-1/rules.d/49-poorsdr-openwebrx.rules >/dev/null <<EOF
// Generado por install.sh de PoorSDR4. Permite start/stop/restart de
// openwebrx.service al grupo 'openwebrx' y al usuario '${USER}' sin autenticacion.
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units") {
        var unit = action.lookup("unit");
        if (unit == "openwebrx.service" &&
            (subject.isInGroup("openwebrx") || subject.user == "${USER}")) {
            return polkit.Result.YES;
        }
    }
});
EOF
  # polkit recarga las reglas solo; forzar por si el servicio esta cacheado.
  sudo systemctl try-restart polkit.service 2>/dev/null || true

  # Respaldo universal: sudoers NOPASSWD acotado a openwebrx.service.
  local sc; sc="$(command -v systemctl || echo /usr/bin/systemctl)"
  local sudoers="/etc/sudoers.d/poorsdr-openwebrx"
  local tmp; tmp="$(mktemp)"
  {
    echo "# Generado por install.sh de PoorSDR4."
    echo "${USER} ALL=(root) NOPASSWD: ${sc} start openwebrx.service, ${sc} stop openwebrx.service, ${sc} restart openwebrx.service, ${sc} is-active openwebrx.service"
  } >"${tmp}"
  if sudo visudo -cf "${tmp}" >/dev/null 2>&1; then
    sudo install -m 440 -o root -g root "${tmp}" "${sudoers}"
    info "sudoers NOPASSWD instalado (${sudoers})."
  else
    warn "La regla sudoers generada no valida; se omite (se usara solo polkit)."
  fi
  rm -f "${tmp}"
}

start_openwebrx_service() {
  log "Preparando openwebrx.service (arranque bajo demanda desde PoorSDR)..."
  sudo systemctl daemon-reload
  # No 'enable': el ciclo de vida lo gobierna PoorSDR (arranca al abrir, para al cerrar).
  sudo systemctl disable openwebrx.service 2>/dev/null || true
  sudo systemctl start openwebrx.service
}

finalize_owrx_service() {
  # Dejar el servicio parado tras verificar: PoorSDR lo arrancara cuando se abra.
  log "Deteniendo openwebrx.service (lo arrancara PoorSDR al abrirse)..."
  sudo systemctl stop openwebrx.service 2>/dev/null || true
}

verify_owrx_http() {
  log "Verificando http://127.0.0.1:${OWRX_PORT}/ ..."
  local i
  for i in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${OWRX_PORT}/" >/dev/null 2>&1; then
      info "OpenWebRX+ responde correctamente."
      return 0
    fi
    sleep 1
  done
  sudo journalctl -u openwebrx.service -n 120 --no-pager >&2 || true
  die "OpenWebRX+ no respondio en el tiempo esperado."
}

install_spider_plugin() {
  [[ "${SKIP_SPIDER}" == "1" ]] && { info "Servicio de spots omitido (SKIP_SPIDER=1)."; return 0; }
  local src="${RUNTIME_DIR}/spiderd"
  [[ -f "${src}/spiderd.py" ]] || { warn "${src}/spiderd.py no encontrado; sin spots."; return 0; }
  log "Instalando spiderd como servicio de USUARIO (spots DX -> ws://127.0.0.1:7373/spots)..."

  local real_user real_home
  real_user="${SUDO_USER:-${USER}}"
  real_home="$(getent passwd "${real_user}" | cut -d: -f6)"
  [[ -n "${real_home}" ]] || real_home="${HOME}"
  local sd_dir="${real_home}/.local/share/poorsdr/spiderd"
  local cfg_dir="${real_home}/.config/poorsdr"
  local unit_dir="${real_home}/.config/systemd/user"

  run_as_user() { sudo -u "${real_user}" env XDG_RUNTIME_DIR="/run/user/$(id -u "${real_user}")" "$@"; }

  if systemctl list-unit-files 2>/dev/null | grep -q "^spiderd\.service"; then
    sudo systemctl disable --now spiderd.service 2>/dev/null || true
  fi
  sudo rm -f /etc/systemd/system/spiderd.service
  sudo systemctl daemon-reload 2>/dev/null || true

  install -d -m 755 "${sd_dir}" "${cfg_dir}" "${unit_dir}"
  install -m 755 "${src}/spiderd.py"       "${sd_dir}/spiderd.py"
  install -m 644 "${src}/requirements.txt" "${sd_dir}/requirements.txt"
  [[ -f "${src}/spiderd_node.mjs" ]]  && install -m 755 "${src}/spiderd_node.mjs"  "${sd_dir}/spiderd_node.mjs"
  [[ -f "${src}/package.json" ]]      && install -m 644 "${src}/package.json"      "${sd_dir}/package.json"
  [[ -f "${src}/package-lock.json" ]] && install -m 644 "${src}/package-lock.json" "${sd_dir}/package-lock.json"

  if [[ -d "${src}/node_modules" ]]; then
    rsync -a --delete "${src}/node_modules/" "${sd_dir}/node_modules/"
  elif command -v npm >/dev/null 2>&1 && [[ -f "${sd_dir}/package-lock.json" ]]; then
    ( cd "${sd_dir}" && npm ci --omit=dev ) || warn "npm ci fallo; spiderd usara el fallback Python."
  fi

  if [[ ! -x "${sd_dir}/venv/bin/python" ]]; then
    python3 -m venv "${sd_dir}/venv" || warn "No se pudo crear el venv de spiderd."
  fi
  if [[ -x "${sd_dir}/venv/bin/pip" ]]; then
    "${sd_dir}/venv/bin/pip" install --quiet --upgrade pip || true
    "${sd_dir}/venv/bin/pip" install --quiet "websockets<16" "paho-mqtt<2" \
      || warn "No se pudieron instalar deps Python de spiderd (si hay Node, funcionara igual)."
  fi

  if [[ ! -f "${cfg_dir}/spiderd.conf" ]]; then
    cat >"${cfg_dir}/spiderd.conf" <<CONF
# Generado por PoorSDR4All. Editable desde Ajustes > Cluster DX / Spots.

[source]
kind = mqtt

[mqtt]
url = wss://ws.ure.es:443/mqtt
topics = spider/spots/dx,spider/spots/rbn-cw,spider/spots/rbn-dig
username =
password =
client_id =
qos = 0
keepalive = 30

[cluster]
host =
port = 7300
user =
password =
read_timeout = 120

[server]
bind = 127.0.0.1
port = 7373
path = /spots

[reconnect]
initial_delay = 3
max_delay = 60

[logging]
level = INFO
CONF
  fi

  cat >"${unit_dir}/spiderd.service" <<UNIT
[Unit]
Description=PoorSDR4 spiderd (spots DX -> ws://127.0.0.1:7373/spots)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=${sd_dir}
ExecStart=${sd_dir}/venv/bin/python ${sd_dir}/spiderd.py --config ${cfg_dir}/spiderd.conf
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
UNIT

  sudo loginctl enable-linger "${real_user}" 2>/dev/null || true

  if run_as_user systemctl --user daemon-reload 2>/dev/null; then
    run_as_user systemctl --user enable --now spiderd.service \
      || warn "spiderd (user) no arranco; revisa: systemctl --user status spiderd"
  else
    warn "Sin bus de usuario ahora; spiderd arrancara al iniciar sesion."
  fi

  local webroot
  webroot="$(python3 - <<PYX 2>/dev/null || true
import importlib.util
s = importlib.util.find_spec("htdocs")
print(next(iter(s.submodule_search_locations)) if s and s.submodule_search_locations else "")
PYX
)"
  if [[ -n "${webroot}" && -d "${webroot}" && -f "${src}/spider.js" ]]; then
    sudo install -d "${webroot}/plugins/receiver/spider"
    sudo install -m644 "${src}/spider.js"  "${webroot}/plugins/receiver/spider/spider.js"
    sudo install -m644 "${src}/spider.css" "${webroot}/plugins/receiver/spider/spider.css"
  fi
}

# --------------------------------------------------------------------------- #
# Estabilidad USB-serie (CAT) para PoorSDR
# --------------------------------------------------------------------------- #
setup_serial_stability() {
  log "Aplicando hardening USB-serie (CAT) persistente..."
  local udev_rule="/etc/udev/rules.d/99-poorsdr4-serial-power.rules"
  sudo tee "${udev_rule}" >/dev/null <<'EOF'
ACTION=="add|change", SUBSYSTEM=="usb", DRIVERS=="ftdi_sio|cp210x|ch341|pl2303|cdc_acm", TEST=="power/control", ATTR{power/control}="on"
ACTION=="add|change", SUBSYSTEM=="tty", KERNEL=="ttyUSB[0-9]*|ttyACM[0-9]*", TEST=="device/power/control", ATTR{device/power/control}="on"
EOF
  local svc="/etc/systemd/system/poorsdr4-serial-power.service"
  sudo tee "${svc}" >/dev/null <<'EOF'
[Unit]
Description=PoorSDR4 serial USB power stability
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'for f in /sys/bus/usb-serial/devices/ttyUSB*/device/power/control /sys/class/tty/ttyACM*/device/power/control; do [ -w "$f" ] && echo on > "$f" || true; done'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  sudo udevadm control --reload-rules >/dev/null 2>&1 || true
  sudo udevadm trigger >/dev/null 2>&1 || true
  sudo systemctl daemon-reload >/dev/null 2>&1 || true
  sudo systemctl enable --now poorsdr4-serial-power.service >/dev/null 2>&1 || true
}

# --------------------------------------------------------------------------- #
# Dependencias Python de PoorSDR
# --------------------------------------------------------------------------- #
install_poorsdr_python_deps() {
  log "Instalando PoorSDR y sus dependencias Python..."
  local py; py="$(command -v python3 || command -v python)"
  [[ -n "${py}" ]] || die "No se encontro Python 3."
  local pipargs=(--user --break-system-packages)
  "${py}" -m pip install "${pipargs[@]}" --upgrade pip
  local target="${PROJECT_DIR}"
  [[ "${INSTALL_WEB_EXTRAS}" == "1" ]] && target="${PROJECT_DIR}[web]"
  "${py}" -m pip install "${pipargs[@]}" "${target}"
}

# --------------------------------------------------------------------------- #
# Fuente LED opcional (7LED, uso personal)
# --------------------------------------------------------------------------- #
install_optional_7led_font() {
  [[ "${INSTALL_7LED_FONT}" == "1" ]] || return 0
  log "Descargando la fuente 7LED desde dafont.com (INSTALL_7LED_FONT=1)..."
  # "Gratis para uso personal": este proyecto no la distribuye ni guarda una
  # copia propia (no hay ningun 7LED.ttf en el repositorio) — se descarga
  # aqui, en el momento de instalar, directo desde la fuente oficial y para
  # el usuario que ejecuta este script, igual que csdr/OpenWebRX+ se clonan
  # de GitHub en vez de venir empaquetados. Si falla por cualquier motivo
  # (sin red, la URL cambio, falta unzip...) no aborta el instalador: la
  # consola sigue funcionando con DSEG7 Classic, que si se instala sola.
  if ! need_cmd curl || ! need_cmd unzip; then
    warn "Falta curl o unzip; no se puede descargar 7LED. Se sigue con DSEG7 Classic."
    return 0
  fi
  local tmp; tmp="$(mktemp -d)"
  if ! curl -fsSL -o "${tmp}/7led.zip" "https://dl.dafont.com/dl/?f=7led"; then
    warn "No se pudo descargar 7LED (dafont.com no respondió). Se sigue con DSEG7 Classic."
    rm -rf "${tmp}"
    return 0
  fi
  local font_dir="${HOME}/.local/share/fonts/7led-personal"
  if ! unzip -oq "${tmp}/7led.zip" '*.ttf' -d "${tmp}" \
     || ! compgen -G "${tmp}/*.ttf" >/dev/null; then
    warn "El zip de 7LED no traía ningún .ttf (¿cambió el paquete en dafont.com?). Se sigue con DSEG7 Classic."
    rm -rf "${tmp}"
    return 0
  fi
  install -d -m 755 "${font_dir}"
  install -m 644 "${tmp}"/*.ttf "${font_dir}/"
  rm -rf "${tmp}"
  command -v fc-cache >/dev/null 2>&1 && fc-cache -f "${font_dir}" >/dev/null 2>&1 || true
  info "7LED instalada en ${font_dir} (uso personal, no redistribuida por este proyecto)."
}

# --------------------------------------------------------------------------- #
main() {
  log "Proyecto: ${PROJECT_DIR}"
  detect_os
  install_system_deps
  build_fft_so

  if [[ "${SKIP_OWRX_BUILD}" == "1" ]]; then
    warn "SKIP_OWRX_BUILD=1: no se (re)compila OpenWebRX+ (solo config/servicio)."
  else
    case "${OS_FAMILY}" in
      arch)   build_openwebrx_stack_arch ;;
      debian) build_openwebrx_stack_debian ;;
    esac
  fi

  # En Arch, openwebrx vive en su venv dedicado (no en el PATH del sistema);
  # en Debian/Ubuntu se instala como paquete .deb, ahi si en el PATH.
  local owrx_installed=0
  if [[ "${OS_FAMILY}" == "arch" ]]; then
    [[ -x "${OWRX_VENV}/bin/openwebrx" ]] && owrx_installed=1
  else
    command -v openwebrx >/dev/null 2>&1 && owrx_installed=1
  fi
  if [[ "${owrx_installed}" == "1" ]]; then
    setup_openwebrx_user
    setup_openwebrx_polkit
    start_openwebrx_service
    install_spider_plugin
    verify_owrx_http
    finalize_owrx_service
  else
    warn "OpenWebRX+ no esta instalado; omitiendo la configuracion del servicio."
  fi

  install_poorsdr_python_deps
  install_optional_7led_font
  setup_serial_stability

  # Grupos para el usuario actual (CAT/PTT por USB-serie desde PoorSDR, y polkit).
  local g
  for g in uucp dialout audio plugdev openwebrx; do
    getent group "${g}" >/dev/null 2>&1 && sudo usermod -aG "${g}" "${USER}" || true
  done

  echo
  log "Instalacion completada."
  info "Arranca PoorSDR con:  python -m poorsdr   (o  ${PROJECT_DIR}/scripts/run.sh )"
  info "OpenWebRX+ arranca solo al abrir PoorSDR y se detiene al cerrarlo."
  info "Estado manual del servicio:  systemctl --user status openwebrx"
  info "IMPORTANTE: cierra sesion y vuelve a entrar para aplicar los grupos nuevos"
  info "(incl. 'openwebrx', necesario para arrancar el servicio sin contrasena)."
  echo
  info "Modos digitales avanzados (DMR/YSF/D-Star/JS8/M17/Pocsag) requieren"
  info "decodificadores extra (digiham, js8py, m17-demod, multimon-ng...)."
  info "FT8/FT4 usan wsjtx (jt9). Instala lo que necesites por separado."
}

main "$@"
