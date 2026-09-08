"""Ayuda contextual (tooltips) de la ventana de Ajustes, por idioma.

Independiente de ``strings.idiomas`` (vocabulario general de la consola,
heredado del proyecto original): esto es texto nuevo, propio del refactor,
para los tooltips de ``ui.settings``. Mismo mecanismo de resolución que
:func:`poorsdr.i18n.t` — cae a español si falta la clave o el idioma.

Las claves con ``{n}``/``{total}`` son plantillas: ``field_help`` acepta
``**kwargs`` y aplica ``.format(**kwargs)`` sobre el texto resuelto.
"""

from __future__ import annotations

DEFAULT_LANG = "es"

HELP: dict[str, dict[str, str]] = {
    "es": {
        "help_cat_port": "Dispositivo serie del cable CAT (p. ej. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' respeta Baudios/PTT por CAT de abajo tal cual. Un perfil "
            "con nombre los sustituye: 'generic-ts480' = uSDX/(tr)uSDX de serie "
            "(38400, PTT por CAT); 'trusdx-115200' = (tr)uSDX firmware ≥2.00t "
            "(115200, sin confirmar en hardware real)."
        ),
        "help_cat_baud": "Ignorado si el perfil de arriba no es 'custom'.",
        "help_cat_control_mode": (
            "'direct' habla directamente con la radio por el puerto CAT. "
            "'hamlib' pasa por un rigctld externo ya en marcha (avanzado)."
        ),
        "help_cat_start_freq_hz": (
            "Frecuencia (en Hz) con la que arranca la consola si la radio no "
            "responde al pedir su estado inicial."
        ),
        "help_cat_step_hz": "Paso de sintonía en Hz al mover el VFO con los botones o el dial.",
        "help_rigctld_enabled": (
            "Activa el proxy rigctld: el puente TCP que usan WSJT-X, N1MM, "
            "FreeDV y otros programas para controlar la radio."
        ),
        "help_rigctld_host": "Dirección donde escucha el proxy rigctld. 127.0.0.1 = solo este equipo.",
        "help_rigctld_port": "Puerto TCP del proxy rigctld (el que configuras en WSJT-X/N1MM como 'rigctld').",
        "help_n1m_enabled": (
            "Emulador de radio Kenwood TS-480 por red, para programas que no "
            "hablan rigctld directamente."
        ),
        "help_n1m_host": "Dirección donde escucha el emulador TS-480.",
        "help_n1m_port": "Puerto TCP del emulador TS-480.",
        "help_audio_rx_source": "De dónde sale el audio de recepción: la SDR (OWRX) o la radio física.",
        "help_audio_speaker_pc": "Salida de audio del PC donde escuchas la recepción.",
        "help_audio_mic_pc": "Entrada de audio del PC (micrófono) para transmitir por voz.",
        "help_audio_speaker_radio": (
            "Entrada de audio desde la radio (lo que la radio recibe, para "
            "pasarlo al PC)."
        ),
        "help_audio_mic_radio": "Salida de audio hacia la radio (lo que el PC envía para transmitir).",
        "help_owrx_enabled": "Activa la integración con OpenWebRX+ (backend, cascada, sintonía compartida).",
        "help_owrx_host": "Dirección donde escucha OpenWebRX+.",
        "help_owrx_port": "Puerto web de OpenWebRX+.",
        "help_owrx_key": "Clave de acceso al panel de OpenWebRX si lo tienes protegido.",
        "help_owrx_runtime": (
            "'native' usa el servicio systemd instalado en este equipo; "
            "'docker' se conecta a un contenedor aparte."
        ),
        "help_owrx_auto_open_on_start": "Abre la ventana de la cascada automáticamente al arrancar la consola.",
        "help_owrx_follow_app_only": (
            "Si se activa, OpenWebRX solo cambia de banda/frecuencia cuando lo "
            "hace PoorSDR; ignora los cambios hechos desde la web de OWRX."
        ),
        "help_owrx_sdr_hint": (
            "Nombre del receptor en OpenWebRX (p. ej. 'RTL-SDR'). Se usa para "
            "elegir el perfil al cambiar de banda. Vacío = autodetectar."
        ),
        "help_owrx_smeter_calibrated": "Usa una escala fija (S9 en el dBFS de abajo) en vez de la autocalibración. Solo tiene sentido si mediste una referencia real con la ganancia del SDR fija (no 'auto').",
        "help_owrx_smeter_s9_dbfs": "dBFS que reporta OWRX exactamente en una señal de referencia conocida como S9 (p. ej. -73 dBm en HF), con la ganancia del SDR fija. Solo se usa si 'S-metro calibrado' está activado.",
        "help_owrx_smeter_noise_floor_s": "Con el S-metro sin calibrar (por defecto), el suelo de ruido/QRM detectado se muestra en esta unidad S, no en S0 — ajústalo al QRM real de tu estación, que no es el mismo en todas partes.",
        "help_owrx_band_profiles": 'Mapa banda→perfil, p. ej. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Minutos que un spot de DX sigue visible en la cascada antes de desaparecer.",
        "help_spider_source": (
            "De dónde llegan los spots del cluster DX: un broker MQTT o un "
            "cluster clásico por Telnet."
        ),
        "help_spider_mqtt_url": "Dirección del broker MQTT (p. ej. mqtt://host:1883) si la fuente es MQTT.",
        "help_spider_mqtt_topics": "Topics MQTT a los que suscribirse, separados por coma.",
        "help_spider_mqtt_user": "Usuario para autenticarse en el broker MQTT (vacío si no hace falta).",
        "help_spider_mqtt_pass": "Contraseña del broker MQTT (vacío si no hace falta).",
        "help_spider_telnet_host": "Dirección del cluster DX por Telnet (p. ej. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Puerto Telnet del cluster DX (normalmente 7300).",
        "help_spider_telnet_call": "Indicativo con el que te identificas al conectar al cluster Telnet.",
        "help_spider_telnet_pass": "Contraseña del cluster Telnet (vacío si no la pide).",
        "help_web_enabled": "Activa el servidor web remoto para controlar la radio desde un navegador.",
        "help_web_host": (
            "Dirección donde escucha el servidor web. 0.0.0.0 = accesible "
            "desde otros equipos de la red."
        ),
        "help_web_port": "Puerto TCP del servidor web.",
        "help_web_allow_wan": (
            "Permite acceso desde fuera de tu red local. Actívalo solo si "
            "sabes lo que haces y usas HTTPS."
        ),
        "help_web_auto_https": "Genera y usa un certificado HTTPS automáticamente en vez de HTTP plano.",
        "help_web_user": "Nombre de usuario para iniciar sesión en el panel web.",
        "help_web_password": (
            "Déjalo vacío para conservar la contraseña actual. Se guarda "
            "salada y con hash, nunca en claro."
        ),
        "help_ui_language": (
            "Idioma de los textos de la consola. (Aún en desarrollo: hoy solo "
            "afecta a algunos textos.)"
        ),
        "help_ui_theme": "Tema de color de la consola y la cascada.",
        "help_ui_display_mode": "Modo de recepción con el que arranca la consola (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Macro {n} de {total}.",
        "help_autocall_name": "Etiqueta libre para identificar el macro; no se envía a la radio.",
        "help_autocall_audio": "Ruta al archivo de audio que se reproduce al disparar el macro.",
        "help_autocall_pick": "Elegir el archivo de audio del macro.",
        "help_autocall_reps": "Veces que se repite el audio al disparar el macro.",
        "help_autocall_interval": "Segundos de pausa entre cada repetición.",
        "help_autocall_button": "Macro que dispara el botón {n} de la consola.",
        "help_hotkeys_capture": (
            "Haz clic y pulsa la tecla que quieras asignar a esta acción. "
            "«Escape» la borra."
        ),
        "help_hotkeys_clear": "Borra el atajo asignado a esta acción.",
        "help_plugins_restart": "Los cambios se aplican al reiniciar PoorSDR.",
        "help_relays_enabled": "Activa el control de relés de filtro por banda vía WiFi (placa ESP).",
        "help_relays_url": "Dirección HTTP de la placa ESP que controla los relés (p. ej. http://192.168.1.50).",
        "help_relays_api_key": "Clave de API de la placa ESP, si la tiene configurada (vacío si no hace falta).",
        "help_relays_timeout_ms": "Milisegundos de espera antes de dar por fallida una petición a la placa ESP.",
        "help_relays_band_groups": 'Mapa banda→grupo de relé, p. ej. {"40m": "40", "20m": "20"}.',
    },
    "en": {
        "help_cat_port": "Serial device for the CAT cable (e.g. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' uses Baudrate/PTT via CAT below as-is. A named profile "
            "overrides them: 'generic-ts480' = stock uSDX/(tr)uSDX (38400, PTT "
            "via CAT); 'trusdx-115200' = (tr)uSDX firmware ≥2.00t (115200, not "
            "yet confirmed on real hardware)."
        ),
        "help_cat_baud": "Ignored unless the profile above is 'custom'.",
        "help_cat_control_mode": (
            "'direct' talks to the radio straight over the CAT port. 'hamlib' "
            "goes through an external rigctld already running (advanced)."
        ),
        "help_cat_start_freq_hz": (
            "Frequency (in Hz) the console starts at if the radio doesn't "
            "answer when asked for its initial state."
        ),
        "help_cat_step_hz": "Tuning step in Hz when moving the VFO with the buttons or the dial.",
        "help_rigctld_enabled": (
            "Enables the rigctld proxy: the TCP bridge WSJT-X, N1MM, FreeDV "
            "and other apps use to control the radio."
        ),
        "help_rigctld_host": "Address the rigctld proxy listens on. 127.0.0.1 = this machine only.",
        "help_rigctld_port": "TCP port of the rigctld proxy (the one you set as 'rigctld' in WSJT-X/N1MM).",
        "help_n1m_enabled": "Kenwood TS-480 network emulator, for programs that don't speak rigctld directly.",
        "help_n1m_host": "Address the TS-480 emulator listens on.",
        "help_n1m_port": "TCP port of the TS-480 emulator.",
        "help_audio_rx_source": "Where the received audio comes from: the SDR (OWRX) or the physical radio.",
        "help_audio_speaker_pc": "PC audio output where you hear the reception.",
        "help_audio_mic_pc": "PC audio input (microphone) for voice transmission.",
        "help_audio_speaker_radio": "Audio input from the radio (what the radio receives, passed to the PC).",
        "help_audio_mic_radio": "Audio output to the radio (what the PC sends to transmit).",
        "help_owrx_enabled": "Enables OpenWebRX+ integration (backend, waterfall, shared tuning).",
        "help_owrx_host": "Address OpenWebRX+ listens on.",
        "help_owrx_port": "OpenWebRX+ web port.",
        "help_owrx_key": "Access key for the OpenWebRX panel if you have it protected.",
        "help_owrx_runtime": (
            "'native' uses the systemd service installed on this machine; "
            "'docker' connects to a separate container."
        ),
        "help_owrx_auto_open_on_start": "Opens the waterfall window automatically when the console starts.",
        "help_owrx_follow_app_only": (
            "When on, OpenWebRX only changes band/frequency when PoorSDR does; "
            "it ignores changes made from the OWRX web UI."
        ),
        "help_owrx_sdr_hint": (
            "Receiver name in OpenWebRX (e.g. 'RTL-SDR'). Used to pick the "
            "profile on band changes. Empty = auto-detect."
        ),
        "help_owrx_smeter_calibrated": "Uses a fixed scale (S9 at the dBFS below) instead of auto-calibration. Only makes sense if you measured a real reference with the SDR gain fixed (not 'auto').",
        "help_owrx_smeter_s9_dbfs": "The dBFS OWRX reports exactly at a known S9 reference signal (e.g. -73 dBm on HF), with the SDR gain fixed. Only used if 'Calibrated S-meter' is enabled.",
        "help_owrx_smeter_noise_floor_s": "With the S-meter uncalibrated (default), the detected noise floor/QRM is shown at this S unit, not S0 — set it to your station's real ambient QRM, which isn't the same everywhere.",
        "help_owrx_band_profiles": 'Band→profile map, e.g. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Minutes a DX spot stays visible on the waterfall before it disappears.",
        "help_spider_source": "Where DX cluster spots come from: an MQTT broker or a classic Telnet cluster.",
        "help_spider_mqtt_url": "MQTT broker address (e.g. mqtt://host:1883) if the source is MQTT.",
        "help_spider_mqtt_topics": "MQTT topics to subscribe to, comma-separated.",
        "help_spider_mqtt_user": "Username to authenticate with the MQTT broker (empty if not needed).",
        "help_spider_mqtt_pass": "MQTT broker password (empty if not needed).",
        "help_spider_telnet_host": "DX cluster Telnet address (e.g. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Telnet port of the DX cluster (usually 7300).",
        "help_spider_telnet_call": "Callsign you identify with when connecting to the Telnet cluster.",
        "help_spider_telnet_pass": "Telnet cluster password (empty if it doesn't ask for one).",
        "help_web_enabled": "Enables the remote web server to control the radio from a browser.",
        "help_web_host": (
            "Address the web server listens on. 0.0.0.0 = reachable from "
            "other machines on the network."
        ),
        "help_web_port": "TCP port of the web server.",
        "help_web_allow_wan": (
            "Allows access from outside your local network. Only enable it "
            "if you know what you're doing and use HTTPS."
        ),
        "help_web_auto_https": "Generates and uses an HTTPS certificate automatically instead of plain HTTP.",
        "help_web_user": "Username to log in to the web panel.",
        "help_web_password": "Leave empty to keep the current password. Stored salted and hashed, never in plain text.",
        "help_ui_language": (
            "Language for the console's text. (Still in progress: today it "
            "only affects some texts.)"
        ),
        "help_ui_theme": "Color theme for the console and the waterfall.",
        "help_ui_display_mode": "Reception mode the console starts in (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Macro {n} of {total}.",
        "help_autocall_name": "Free-text label to identify the macro; it isn't sent to the radio.",
        "help_autocall_audio": "Path to the audio file played when the macro fires.",
        "help_autocall_pick": "Choose the macro's audio file.",
        "help_autocall_reps": "Times the audio repeats when the macro fires.",
        "help_autocall_interval": "Seconds of pause between each repetition.",
        "help_autocall_button": "Macro triggered by console button {n}.",
        "help_hotkeys_capture": "Click, then press the key you want to assign to this action. 'Escape' clears it.",
        "help_hotkeys_clear": "Clears the hotkey assigned to this action.",
        "help_plugins_restart": "Changes apply when PoorSDR restarts.",
        "help_relays_enabled": "Enables band filter relay control over WiFi (ESP board).",
        "help_relays_url": "HTTP address of the ESP board that controls the relays (e.g. http://192.168.1.50).",
        "help_relays_api_key": "API key for the ESP board, if it has one configured (empty if not needed).",
        "help_relays_timeout_ms": "Milliseconds to wait before treating a request to the ESP board as failed.",
        "help_relays_band_groups": 'Band→relay group map, e.g. {"40m": "40", "20m": "20"}.',
    },
    "fr": {
        "help_cat_port": "Périphérique série du câble CAT (p. ex. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' respecte tel quel le débit/PTT par CAT ci-dessous. Un "
            "profil nommé les remplace : 'generic-ts480' = uSDX/(tr)uSDX de "
            "série (38400, PTT par CAT) ; 'trusdx-115200' = (tr)uSDX firmware "
            "≥2.00t (115200, non confirmé sur matériel réel)."
        ),
        "help_cat_baud": "Ignoré si le profil ci-dessus n'est pas 'custom'.",
        "help_cat_control_mode": (
            "'direct' parle directement à la radio via le port CAT. 'hamlib' "
            "passe par un rigctld externe déjà lancé (avancé)."
        ),
        "help_cat_start_freq_hz": (
            "Fréquence (en Hz) au démarrage de la console si la radio ne "
            "répond pas à la demande d'état initial."
        ),
        "help_cat_step_hz": "Pas de syntonisation en Hz en déplaçant le VFO avec les boutons ou la molette.",
        "help_rigctld_enabled": (
            "Active le proxy rigctld : le pont TCP utilisé par WSJT-X, N1MM, "
            "FreeDV et d'autres programmes pour piloter la radio."
        ),
        "help_rigctld_host": "Adresse d'écoute du proxy rigctld. 127.0.0.1 = cette machine seulement.",
        "help_rigctld_port": "Port TCP du proxy rigctld (celui configuré comme 'rigctld' dans WSJT-X/N1MM).",
        "help_n1m_enabled": "Émulateur réseau Kenwood TS-480, pour les programmes qui ne parlent pas rigctld directement.",
        "help_n1m_host": "Adresse d'écoute de l'émulateur TS-480.",
        "help_n1m_port": "Port TCP de l'émulateur TS-480.",
        "help_audio_rx_source": "D'où vient l'audio de réception : le SDR (OWRX) ou la radio physique.",
        "help_audio_speaker_pc": "Sortie audio du PC où vous entendez la réception.",
        "help_audio_mic_pc": "Entrée audio du PC (microphone) pour l'émission vocale.",
        "help_audio_speaker_radio": "Entrée audio depuis la radio (ce que la radio reçoit, transmis au PC).",
        "help_audio_mic_radio": "Sortie audio vers la radio (ce que le PC envoie pour émettre).",
        "help_owrx_enabled": "Active l'intégration OpenWebRX+ (backend, cascade, syntonisation partagée).",
        "help_owrx_host": "Adresse d'écoute d'OpenWebRX+.",
        "help_owrx_port": "Port web d'OpenWebRX+.",
        "help_owrx_key": "Clé d'accès au panneau OpenWebRX si celui-ci est protégé.",
        "help_owrx_runtime": (
            "'native' utilise le service systemd installé sur cette machine ; "
            "'docker' se connecte à un conteneur séparé."
        ),
        "help_owrx_auto_open_on_start": "Ouvre automatiquement la fenêtre de la cascade au démarrage de la console.",
        "help_owrx_follow_app_only": (
            "Si activé, OpenWebRX ne change de bande/fréquence que via "
            "PoorSDR ; il ignore les changements faits depuis le web OWRX."
        ),
        "help_owrx_sdr_hint": (
            "Nom du récepteur dans OpenWebRX (p. ex. 'RTL-SDR'). Utilisé pour "
            "choisir le profil au changement de bande. Vide = détection "
            "automatique."
        ),
        "help_owrx_smeter_calibrated": "Utilise une échelle fixe (S9 au dBFS ci-dessous) au lieu de l'autocalibrage. N'a de sens que si vous avez mesuré une référence réelle avec le gain du SDR fixe (pas « auto »).",
        "help_owrx_smeter_s9_dbfs": "Le dBFS que rapporte OWRX exactement sur un signal de référence S9 connu (p. ex. -73 dBm en HF), avec le gain du SDR fixe. Utilisé seulement si « S-mètre calibré » est activé.",
        "help_owrx_smeter_noise_floor_s": "Avec le S-mètre non calibré (par défaut), le bruit de fond/QRM détecté s'affiche à cette unité S, pas à S0 — réglez-le sur le QRM réel de votre station, qui varie d'un endroit à l'autre.",
        "help_owrx_band_profiles": 'Correspondance bande→profil, p. ex. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Minutes pendant lesquelles un spot DX reste visible sur la cascade avant de disparaître.",
        "help_spider_source": "D'où viennent les spots du cluster DX : un broker MQTT ou un cluster Telnet classique.",
        "help_spider_mqtt_url": "Adresse du broker MQTT (p. ex. mqtt://host:1883) si la source est MQTT.",
        "help_spider_mqtt_topics": "Topics MQTT auxquels s'abonner, séparés par des virgules.",
        "help_spider_mqtt_user": "Utilisateur pour s'authentifier auprès du broker MQTT (vide si inutile).",
        "help_spider_mqtt_pass": "Mot de passe du broker MQTT (vide si inutile).",
        "help_spider_telnet_host": "Adresse Telnet du cluster DX (p. ex. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Port Telnet du cluster DX (généralement 7300).",
        "help_spider_telnet_call": "Indicatif utilisé pour s'identifier en se connectant au cluster Telnet.",
        "help_spider_telnet_pass": "Mot de passe du cluster Telnet (vide s'il n'en demande pas).",
        "help_web_enabled": "Active le serveur web distant pour piloter la radio depuis un navigateur.",
        "help_web_host": (
            "Adresse d'écoute du serveur web. 0.0.0.0 = accessible depuis "
            "d'autres machines du réseau."
        ),
        "help_web_port": "Port TCP du serveur web.",
        "help_web_allow_wan": (
            "Autorise l'accès depuis l'extérieur du réseau local. À activer "
            "seulement en connaissance de cause, avec HTTPS."
        ),
        "help_web_auto_https": "Génère et utilise automatiquement un certificat HTTPS au lieu du HTTP simple.",
        "help_web_user": "Nom d'utilisateur pour se connecter au panneau web.",
        "help_web_password": "Laissez vide pour conserver le mot de passe actuel. Stocké salé et haché, jamais en clair.",
        "help_ui_language": (
            "Langue des textes de la console. (Encore en développement : "
            "n'affecte aujourd'hui que certains textes.)"
        ),
        "help_ui_theme": "Thème de couleur de la console et de la cascade.",
        "help_ui_display_mode": "Mode de réception au démarrage de la console (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Macro {n} sur {total}.",
        "help_autocall_name": "Étiquette libre pour identifier le macro ; non envoyée à la radio.",
        "help_autocall_audio": "Chemin du fichier audio joué au déclenchement du macro.",
        "help_autocall_pick": "Choisir le fichier audio du macro.",
        "help_autocall_reps": "Nombre de répétitions de l'audio au déclenchement du macro.",
        "help_autocall_interval": "Secondes de pause entre chaque répétition.",
        "help_autocall_button": "Macro déclenché par le bouton {n} de la console.",
        "help_hotkeys_capture": "Cliquez puis appuyez sur la touche à assigner à cette action. « Échap » l'efface.",
        "help_hotkeys_clear": "Efface le raccourci assigné à cette action.",
        "help_plugins_restart": "Les changements s'appliquent au redémarrage de PoorSDR.",
        "help_relays_enabled": "Active le contrôle des relais de filtre par bande via WiFi (carte ESP).",
        "help_relays_url": "Adresse HTTP de la carte ESP qui contrôle les relais (p. ex. http://192.168.1.50).",
        "help_relays_api_key": "Clé API de la carte ESP, si elle en a une configurée (vide si inutile).",
        "help_relays_timeout_ms": "Millisecondes d'attente avant de considérer une requête à la carte ESP comme échouée.",
        "help_relays_band_groups": 'Correspondance bande→groupe de relais, p. ex. {"40m": "40", "20m": "20"}.',
    },
    "de": {
        "help_cat_port": "Serielles Gerät des CAT-Kabels (z. B. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' übernimmt Baudrate/PTT über CAT unten unverändert. Ein "
            "benanntes Profil ersetzt sie: 'generic-ts480' = uSDX/(tr)uSDX "
            "Standard (38400, PTT über CAT); 'trusdx-115200' = (tr)uSDX "
            "Firmware ≥2.00t (115200, an echter Hardware noch nicht "
            "bestätigt)."
        ),
        "help_cat_baud": "Wird ignoriert, wenn das Profil oben nicht 'custom' ist.",
        "help_cat_control_mode": (
            "'direct' spricht direkt über den CAT-Port mit dem Funkgerät. "
            "'hamlib' geht über ein bereits laufendes externes rigctld "
            "(fortgeschritten)."
        ),
        "help_cat_start_freq_hz": (
            "Frequenz (in Hz), mit der die Konsole startet, falls das "
            "Funkgerät auf die Abfrage des Anfangszustands nicht antwortet."
        ),
        "help_cat_step_hz": "Abstimmschritt in Hz beim Bewegen des VFO mit den Tasten oder dem Rad.",
        "help_rigctld_enabled": (
            "Aktiviert den rigctld-Proxy: die TCP-Brücke, über die WSJT-X, "
            "N1MM, FreeDV und andere Programme das Funkgerät steuern."
        ),
        "help_rigctld_host": "Adresse, auf der der rigctld-Proxy lauscht. 127.0.0.1 = nur dieser Rechner.",
        "help_rigctld_port": "TCP-Port des rigctld-Proxys (der in WSJT-X/N1MM als 'rigctld' eingestellt wird).",
        "help_n1m_enabled": "Kenwood-TS-480-Netzwerkemulator für Programme, die nicht direkt rigctld sprechen.",
        "help_n1m_host": "Adresse, auf der der TS-480-Emulator lauscht.",
        "help_n1m_port": "TCP-Port des TS-480-Emulators.",
        "help_audio_rx_source": "Woher das Empfangsaudio kommt: der SDR (OWRX) oder das physische Funkgerät.",
        "help_audio_speaker_pc": "PC-Audioausgang, über den der Empfang zu hören ist.",
        "help_audio_mic_pc": "PC-Audioeingang (Mikrofon) zum Senden per Sprache.",
        "help_audio_speaker_radio": "Audioeingang vom Funkgerät (was das Funkgerät empfängt, an den PC weitergeleitet).",
        "help_audio_mic_radio": "Audioausgang zum Funkgerät (was der PC zum Senden ausgibt).",
        "help_owrx_enabled": "Aktiviert die OpenWebRX+-Integration (Backend, Wasserfall, gemeinsame Abstimmung).",
        "help_owrx_host": "Adresse, auf der OpenWebRX+ lauscht.",
        "help_owrx_port": "Web-Port von OpenWebRX+.",
        "help_owrx_key": "Zugriffsschlüssel für das OpenWebRX-Panel, falls geschützt.",
        "help_owrx_runtime": (
            "'native' nutzt den auf diesem Rechner installierten "
            "systemd-Dienst; 'docker' verbindet sich mit einem separaten "
            "Container."
        ),
        "help_owrx_auto_open_on_start": "Öffnet das Wasserfallfenster automatisch beim Start der Konsole.",
        "help_owrx_follow_app_only": (
            "Wenn aktiv, ändert OpenWebRX Band/Frequenz nur, wenn PoorSDR es "
            "tut; Änderungen aus dem OWRX-Web werden ignoriert."
        ),
        "help_owrx_sdr_hint": (
            "Empfängername in OpenWebRX (z. B. 'RTL-SDR'). Dient zur "
            "Profilwahl beim Bandwechsel. Leer = automatisch erkennen."
        ),
        "help_owrx_smeter_calibrated": "Verwendet eine feste Skala (S9 beim dBFS unten) statt der Autokalibrierung. Ergibt nur Sinn, wenn du eine echte Referenz mit fester SDR-Verstärkung (nicht 'auto') gemessen hast.",
        "help_owrx_smeter_s9_dbfs": "Der dBFS-Wert, den OWRX genau bei einem bekannten S9-Referenzsignal meldet (z. B. -73 dBm auf KW), bei fester SDR-Verstärkung. Wird nur verwendet, wenn 'S-Meter kalibriert' aktiviert ist.",
        "help_owrx_smeter_noise_floor_s": "Bei unkalibriertem S-Meter (Standard) wird der erkannte Rauschboden/QRM auf dieser S-Einheit angezeigt, nicht auf S0 — stellen Sie ihn auf das tatsächliche Umgebungs-QRM Ihrer Station ein, das nicht überall gleich ist.",
        "help_owrx_band_profiles": 'Zuordnung Band→Profil, z. B. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Minuten, die ein DX-Spot im Wasserfall sichtbar bleibt, bevor er verschwindet.",
        "help_spider_source": "Woher die DX-Cluster-Spots kommen: ein MQTT-Broker oder ein klassischer Telnet-Cluster.",
        "help_spider_mqtt_url": "Adresse des MQTT-Brokers (z. B. mqtt://host:1883), wenn die Quelle MQTT ist.",
        "help_spider_mqtt_topics": "MQTT-Topics zum Abonnieren, kommagetrennt.",
        "help_spider_mqtt_user": "Benutzername zur Anmeldung beim MQTT-Broker (leer, falls nicht nötig).",
        "help_spider_mqtt_pass": "Passwort des MQTT-Brokers (leer, falls nicht nötig).",
        "help_spider_telnet_host": "Telnet-Adresse des DX-Clusters (z. B. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Telnet-Port des DX-Clusters (üblicherweise 7300).",
        "help_spider_telnet_call": "Rufzeichen, mit dem man sich beim Verbinden zum Telnet-Cluster identifiziert.",
        "help_spider_telnet_pass": "Passwort des Telnet-Clusters (leer, falls keins verlangt wird).",
        "help_web_enabled": "Aktiviert den entfernten Webserver, um das Funkgerät über einen Browser zu steuern.",
        "help_web_host": (
            "Adresse, auf der der Webserver lauscht. 0.0.0.0 = von anderen "
            "Rechnern im Netzwerk erreichbar."
        ),
        "help_web_port": "TCP-Port des Webservers.",
        "help_web_allow_wan": (
            "Erlaubt Zugriff von außerhalb des lokalen Netzwerks. Nur "
            "aktivieren, wenn man weiß, was man tut, und HTTPS nutzt."
        ),
        "help_web_auto_https": "Erzeugt und nutzt automatisch ein HTTPS-Zertifikat statt einfachem HTTP.",
        "help_web_user": "Benutzername für die Anmeldung im Web-Panel.",
        "help_web_password": "Leer lassen, um das aktuelle Passwort zu behalten. Gespeichert gesalzen und gehasht, nie im Klartext.",
        "help_ui_language": (
            "Sprache der Konsolentexte. (Noch in Arbeit: betrifft heute nur "
            "einige Texte.)"
        ),
        "help_ui_theme": "Farbthema von Konsole und Wasserfall.",
        "help_ui_display_mode": "Empfangsmodus, mit dem die Konsole startet (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Makro {n} von {total}.",
        "help_autocall_name": "Freier Bezeichner zur Erkennung des Makros; wird nicht an das Funkgerät gesendet.",
        "help_autocall_audio": "Pfad zur Audiodatei, die beim Auslösen des Makros abgespielt wird.",
        "help_autocall_pick": "Audiodatei des Makros auswählen.",
        "help_autocall_reps": "Wie oft das Audio beim Auslösen des Makros wiederholt wird.",
        "help_autocall_interval": "Sekunden Pause zwischen jeder Wiederholung.",
        "help_autocall_button": "Makro, das von Konsolentaste {n} ausgelöst wird.",
        "help_hotkeys_capture": (
            "Klicken und dann die Taste drücken, die dieser Aktion zugewiesen "
            "werden soll. „Escape“ löscht sie."
        ),
        "help_hotkeys_clear": "Löscht das dieser Aktion zugewiesene Tastenkürzel.",
        "help_plugins_restart": "Änderungen wirken nach einem Neustart von PoorSDR.",
        "help_relays_enabled": "Aktiviert die Steuerung der Bandfilter-Relais über WLAN (ESP-Board).",
        "help_relays_url": "HTTP-Adresse des ESP-Boards, das die Relais steuert (z. B. http://192.168.1.50).",
        "help_relays_api_key": "API-Schlüssel des ESP-Boards, falls konfiguriert (leer, falls nicht nötig).",
        "help_relays_timeout_ms": "Millisekunden Wartezeit, bevor eine Anfrage an das ESP-Board als fehlgeschlagen gilt.",
        "help_relays_band_groups": 'Zuordnung Band→Relaisgruppe, z. B. {"40m": "40", "20m": "20"}.',
    },
    "it": {
        "help_cat_port": "Dispositivo seriale del cavo CAT (es. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' usa Baud/PTT via CAT qui sotto così come sono. Un "
            "profilo con nome li sostituisce: 'generic-ts480' = uSDX/(tr)uSDX "
            "di serie (38400, PTT via CAT); 'trusdx-115200' = (tr)uSDX "
            "firmware ≥2.00t (115200, non ancora confermato su hardware "
            "reale)."
        ),
        "help_cat_baud": "Ignorato se il profilo sopra non è 'custom'.",
        "help_cat_control_mode": (
            "'direct' parla direttamente con la radio via porta CAT. "
            "'hamlib' passa da un rigctld esterno già in esecuzione "
            "(avanzato)."
        ),
        "help_cat_start_freq_hz": (
            "Frequenza (in Hz) con cui parte la console se la radio non "
            "risponde alla richiesta di stato iniziale."
        ),
        "help_cat_step_hz": "Passo di sintonia in Hz muovendo il VFO con i pulsanti o la manopola.",
        "help_rigctld_enabled": (
            "Attiva il proxy rigctld: il ponte TCP usato da WSJT-X, N1MM, "
            "FreeDV e altri programmi per controllare la radio."
        ),
        "help_rigctld_host": "Indirizzo su cui ascolta il proxy rigctld. 127.0.0.1 = solo questo computer.",
        "help_rigctld_port": "Porta TCP del proxy rigctld (quella impostata come 'rigctld' in WSJT-X/N1MM).",
        "help_n1m_enabled": "Emulatore di rete Kenwood TS-480, per programmi che non parlano rigctld direttamente.",
        "help_n1m_host": "Indirizzo su cui ascolta l'emulatore TS-480.",
        "help_n1m_port": "Porta TCP dell'emulatore TS-480.",
        "help_audio_rx_source": "Da dove arriva l'audio di ricezione: l'SDR (OWRX) o la radio fisica.",
        "help_audio_speaker_pc": "Uscita audio del PC dove ascolti la ricezione.",
        "help_audio_mic_pc": "Ingresso audio del PC (microfono) per trasmettere in fonia.",
        "help_audio_speaker_radio": "Ingresso audio dalla radio (ciò che la radio riceve, passato al PC).",
        "help_audio_mic_radio": "Uscita audio verso la radio (ciò che il PC invia per trasmettere).",
        "help_owrx_enabled": "Attiva l'integrazione con OpenWebRX+ (backend, cascata, sintonia condivisa).",
        "help_owrx_host": "Indirizzo su cui ascolta OpenWebRX+.",
        "help_owrx_port": "Porta web di OpenWebRX+.",
        "help_owrx_key": "Chiave di accesso al pannello OpenWebRX se protetto.",
        "help_owrx_runtime": (
            "'native' usa il servizio systemd installato su questo computer; "
            "'docker' si connette a un container separato."
        ),
        "help_owrx_auto_open_on_start": "Apre automaticamente la finestra della cascata all'avvio della console.",
        "help_owrx_follow_app_only": (
            "Se attivo, OpenWebRX cambia banda/frequenza solo quando lo fa "
            "PoorSDR; ignora i cambi fatti dal web di OWRX."
        ),
        "help_owrx_sdr_hint": (
            "Nome del ricevitore in OpenWebRX (es. 'RTL-SDR'). Usato per "
            "scegliere il profilo al cambio banda. Vuoto = rilevamento "
            "automatico."
        ),
        "help_owrx_smeter_calibrated": "Usa una scala fissa (S9 al dBFS sotto) invece dell'autocalibrazione. Ha senso solo se hai misurato un riferimento reale con il guadagno dell'SDR fisso (non 'auto').",
        "help_owrx_smeter_s9_dbfs": "Il dBFS che OWRX riporta esattamente su un segnale di riferimento S9 noto (es. -73 dBm in HF), con il guadagno dell'SDR fisso. Usato solo se 'S-metro calibrato' è attivo.",
        "help_owrx_smeter_noise_floor_s": "Con l'S-metro non calibrato (predefinito), il rumore di fondo/QRM rilevato viene mostrato a questa unità S, non a S0 — impostalo sul QRM ambientale reale della tua stazione, che non è uguale ovunque.",
        "help_owrx_band_profiles": 'Mappa banda→profilo, es. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Minuti in cui uno spot DX resta visibile sulla cascata prima di sparire.",
        "help_spider_source": "Da dove arrivano gli spot del cluster DX: un broker MQTT o un cluster Telnet classico.",
        "help_spider_mqtt_url": "Indirizzo del broker MQTT (es. mqtt://host:1883) se la fonte è MQTT.",
        "help_spider_mqtt_topics": "Topic MQTT a cui iscriversi, separati da virgola.",
        "help_spider_mqtt_user": "Utente per autenticarsi sul broker MQTT (vuoto se non serve).",
        "help_spider_mqtt_pass": "Password del broker MQTT (vuoto se non serve).",
        "help_spider_telnet_host": "Indirizzo Telnet del cluster DX (es. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Porta Telnet del cluster DX (di solito 7300).",
        "help_spider_telnet_call": "Nominativo con cui ci si identifica connettendosi al cluster Telnet.",
        "help_spider_telnet_pass": "Password del cluster Telnet (vuoto se non richiesta).",
        "help_web_enabled": "Attiva il server web remoto per controllare la radio da un browser.",
        "help_web_host": (
            "Indirizzo su cui ascolta il server web. 0.0.0.0 = raggiungibile "
            "da altri computer in rete."
        ),
        "help_web_port": "Porta TCP del server web.",
        "help_web_allow_wan": (
            "Consente l'accesso da fuori la rete locale. Attivalo solo se "
            "sai cosa fai e usi HTTPS."
        ),
        "help_web_auto_https": "Genera e usa automaticamente un certificato HTTPS invece di HTTP semplice.",
        "help_web_user": "Nome utente per accedere al pannello web.",
        "help_web_password": "Lascia vuoto per mantenere la password attuale. Salvata salata e con hash, mai in chiaro.",
        "help_ui_language": (
            "Lingua dei testi della console. (Ancora in sviluppo: oggi "
            "riguarda solo alcuni testi.)"
        ),
        "help_ui_theme": "Tema colore della console e della cascata.",
        "help_ui_display_mode": "Modo di ricezione con cui parte la console (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Macro {n} di {total}.",
        "help_autocall_name": "Etichetta libera per identificare il macro; non viene inviata alla radio.",
        "help_autocall_audio": "Percorso del file audio riprodotto all'attivazione del macro.",
        "help_autocall_pick": "Scegli il file audio del macro.",
        "help_autocall_reps": "Numero di ripetizioni dell'audio all'attivazione del macro.",
        "help_autocall_interval": "Secondi di pausa tra ogni ripetizione.",
        "help_autocall_button": "Macro attivato dal pulsante {n} della console.",
        "help_hotkeys_capture": "Clicca e poi premi il tasto da assegnare a questa azione. «Esc» lo cancella.",
        "help_hotkeys_clear": "Cancella la scorciatoia assegnata a questa azione.",
        "help_plugins_restart": "Le modifiche si applicano al riavvio di PoorSDR.",
        "help_relays_enabled": "Attiva il controllo dei relè filtro per banda via WiFi (scheda ESP).",
        "help_relays_url": "Indirizzo HTTP della scheda ESP che controlla i relè (es. http://192.168.1.50).",
        "help_relays_api_key": "Chiave API della scheda ESP, se configurata (vuoto se non serve).",
        "help_relays_timeout_ms": "Millisecondi di attesa prima di considerare fallita una richiesta alla scheda ESP.",
        "help_relays_band_groups": 'Mappa banda→gruppo relè, es. {"40m": "40", "20m": "20"}.',
    },
    "pt": {
        "help_cat_port": "Dispositivo série do cabo CAT (ex. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' usa Baud/PTT por CAT abaixo tal como estão. Um perfil "
            "com nome substitui-os: 'generic-ts480' = uSDX/(tr)uSDX de série "
            "(38400, PTT por CAT); 'trusdx-115200' = (tr)uSDX firmware "
            "≥2.00t (115200, ainda não confirmado em hardware real)."
        ),
        "help_cat_baud": "Ignorado se o perfil acima não for 'custom'.",
        "help_cat_control_mode": (
            "'direct' fala diretamente com o rádio pela porta CAT. 'hamlib' "
            "passa por um rigctld externo já em execução (avançado)."
        ),
        "help_cat_start_freq_hz": (
            "Frequência (em Hz) com que a consola arranca se o rádio não "
            "responder ao pedido de estado inicial."
        ),
        "help_cat_step_hz": "Passo de sintonia em Hz ao mover o VFO com os botões ou o dial.",
        "help_rigctld_enabled": (
            "Ativa o proxy rigctld: a ponte TCP usada pelo WSJT-X, N1MM, "
            "FreeDV e outros programas para controlar o rádio."
        ),
        "help_rigctld_host": "Endereço onde o proxy rigctld escuta. 127.0.0.1 = só este computador.",
        "help_rigctld_port": "Porta TCP do proxy rigctld (a definida como 'rigctld' no WSJT-X/N1MM).",
        "help_n1m_enabled": "Emulador de rede Kenwood TS-480, para programas que não falam rigctld diretamente.",
        "help_n1m_host": "Endereço onde o emulador TS-480 escuta.",
        "help_n1m_port": "Porta TCP do emulador TS-480.",
        "help_audio_rx_source": "De onde vem o áudio de receção: o SDR (OWRX) ou o rádio físico.",
        "help_audio_speaker_pc": "Saída de áudio do PC onde ouves a receção.",
        "help_audio_mic_pc": "Entrada de áudio do PC (microfone) para transmitir por voz.",
        "help_audio_speaker_radio": "Entrada de áudio do rádio (o que o rádio recebe, passado ao PC).",
        "help_audio_mic_radio": "Saída de áudio para o rádio (o que o PC envia para transmitir).",
        "help_owrx_enabled": "Ativa a integração com o OpenWebRX+ (backend, cascata, sintonia partilhada).",
        "help_owrx_host": "Endereço onde o OpenWebRX+ escuta.",
        "help_owrx_port": "Porta web do OpenWebRX+.",
        "help_owrx_key": "Chave de acesso ao painel OpenWebRX se estiver protegido.",
        "help_owrx_runtime": (
            "'native' usa o serviço systemd instalado neste computador; "
            "'docker' liga-se a um contentor separado."
        ),
        "help_owrx_auto_open_on_start": "Abre a janela da cascata automaticamente ao arrancar a consola.",
        "help_owrx_follow_app_only": (
            "Se ativo, o OpenWebRX só muda de banda/frequência quando o "
            "PoorSDR o faz; ignora alterações feitas na web do OWRX."
        ),
        "help_owrx_sdr_hint": (
            "Nome do recetor no OpenWebRX (ex. 'RTL-SDR'). Usado para "
            "escolher o perfil ao mudar de banda. Vazio = deteção "
            "automática."
        ),
        "help_owrx_smeter_calibrated": "Usa uma escala fixa (S9 no dBFS abaixo) em vez da autocalibração. Só faz sentido se mediu uma referência real com o ganho do SDR fixo (não 'auto').",
        "help_owrx_smeter_s9_dbfs": "O dBFS que o OWRX reporta exatamente num sinal de referência S9 conhecido (ex. -73 dBm em HF), com o ganho do SDR fixo. Só se usa se 'S-metro calibrado' estiver ativo.",
        "help_owrx_smeter_noise_floor_s": "Com o S-metro não calibrado (padrão), o ruído de fundo/QRM detetado é mostrado nesta unidade S, não em S0 — ajuste ao QRM ambiente real da sua estação, que não é igual em todo o lado.",
        "help_owrx_band_profiles": 'Mapa banda→perfil, ex. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Minutos em que um spot DX fica visível na cascata antes de desaparecer.",
        "help_spider_source": "De onde vêm os spots do cluster DX: um broker MQTT ou um cluster Telnet clássico.",
        "help_spider_mqtt_url": "Endereço do broker MQTT (ex. mqtt://host:1883) se a fonte for MQTT.",
        "help_spider_mqtt_topics": "Tópicos MQTT a subscrever, separados por vírgula.",
        "help_spider_mqtt_user": "Utilizador para autenticação no broker MQTT (vazio se não for preciso).",
        "help_spider_mqtt_pass": "Palavra-passe do broker MQTT (vazio se não for preciso).",
        "help_spider_telnet_host": "Endereço Telnet do cluster DX (ex. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Porta Telnet do cluster DX (normalmente 7300).",
        "help_spider_telnet_call": "Indicativo com que te identificas ao ligar ao cluster Telnet.",
        "help_spider_telnet_pass": "Palavra-passe do cluster Telnet (vazio se não for pedida).",
        "help_web_enabled": "Ativa o servidor web remoto para controlar o rádio a partir de um browser.",
        "help_web_host": (
            "Endereço onde o servidor web escuta. 0.0.0.0 = acessível a "
            "partir de outros computadores da rede."
        ),
        "help_web_port": "Porta TCP do servidor web.",
        "help_web_allow_wan": (
            "Permite acesso a partir de fora da rede local. Ative só se "
            "souber o que faz e usar HTTPS."
        ),
        "help_web_auto_https": "Gera e usa automaticamente um certificado HTTPS em vez de HTTP simples.",
        "help_web_user": "Nome de utilizador para iniciar sessão no painel web.",
        "help_web_password": "Deixe vazio para manter a palavra-passe atual. Guardada com sal e hash, nunca em texto simples.",
        "help_ui_language": (
            "Idioma dos textos da consola. (Ainda em desenvolvimento: hoje "
            "só afeta alguns textos.)"
        ),
        "help_ui_theme": "Tema de cor da consola e da cascata.",
        "help_ui_display_mode": "Modo de receção com que a consola arranca (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Macro {n} de {total}.",
        "help_autocall_name": "Etiqueta livre para identificar o macro; não é enviada ao rádio.",
        "help_autocall_audio": "Caminho do ficheiro áudio reproduzido ao disparar o macro.",
        "help_autocall_pick": "Escolher o ficheiro áudio do macro.",
        "help_autocall_reps": "Vezes que o áudio repete ao disparar o macro.",
        "help_autocall_interval": "Segundos de pausa entre cada repetição.",
        "help_autocall_button": "Macro disparado pelo botão {n} da consola.",
        "help_hotkeys_capture": "Clica e depois pressiona a tecla a atribuir a esta ação. «Escape» apaga-a.",
        "help_hotkeys_clear": "Apaga o atalho atribuído a esta ação.",
        "help_plugins_restart": "As alterações aplicam-se ao reiniciar o PoorSDR.",
        "help_relays_enabled": "Ativa o controlo dos relés de filtro por banda via WiFi (placa ESP).",
        "help_relays_url": "Endereço HTTP da placa ESP que controla os relés (ex. http://192.168.1.50).",
        "help_relays_api_key": "Chave de API da placa ESP, se estiver configurada (vazio se não for preciso).",
        "help_relays_timeout_ms": "Milissegundos de espera antes de considerar falhado um pedido à placa ESP.",
        "help_relays_band_groups": 'Mapa banda→grupo de relé, ex. {"40m": "40", "20m": "20"}.',
    },
    "ca": {
        "help_cat_port": "Dispositiu sèrie del cable CAT (p. ex. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' respecta Bauds/PTT per CAT de sota tal com estan. Un "
            "perfil amb nom els substitueix: 'generic-ts480' = uSDX/(tr)uSDX "
            "de sèrie (38400, PTT per CAT); 'trusdx-115200' = (tr)uSDX "
            "firmware ≥2.00t (115200, encara sense confirmar en maquinari "
            "real)."
        ),
        "help_cat_baud": "Ignorat si el perfil de dalt no és 'custom'.",
        "help_cat_control_mode": (
            "'direct' parla directament amb la ràdio pel port CAT. 'hamlib' "
            "passa per un rigctld extern ja en marxa (avançat)."
        ),
        "help_cat_start_freq_hz": (
            "Freqüència (en Hz) amb què arrenca la consola si la ràdio no "
            "respon en demanar el seu estat inicial."
        ),
        "help_cat_step_hz": "Pas de sintonia en Hz en moure el VFO amb els botons o el dial.",
        "help_rigctld_enabled": (
            "Activa el proxy rigctld: el pont TCP que fan servir WSJT-X, "
            "N1MM, FreeDV i altres programes per controlar la ràdio."
        ),
        "help_rigctld_host": "Adreça on escolta el proxy rigctld. 127.0.0.1 = només aquest equip.",
        "help_rigctld_port": "Port TCP del proxy rigctld (el que es configura com a 'rigctld' a WSJT-X/N1MM).",
        "help_n1m_enabled": "Emulador de ràdio Kenwood TS-480 per xarxa, per a programes que no parlen rigctld directament.",
        "help_n1m_host": "Adreça on escolta l'emulador TS-480.",
        "help_n1m_port": "Port TCP de l'emulador TS-480.",
        "help_audio_rx_source": "D'on surt l'àudio de recepció: l'SDR (OWRX) o la ràdio física.",
        "help_audio_speaker_pc": "Sortida d'àudio del PC on escoltes la recepció.",
        "help_audio_mic_pc": "Entrada d'àudio del PC (micròfon) per transmetre per veu.",
        "help_audio_speaker_radio": "Entrada d'àudio des de la ràdio (el que la ràdio rep, passat al PC).",
        "help_audio_mic_radio": "Sortida d'àudio cap a la ràdio (el que el PC envia per transmetre).",
        "help_owrx_enabled": "Activa la integració amb OpenWebRX+ (backend, cascada, sintonia compartida).",
        "help_owrx_host": "Adreça on escolta OpenWebRX+.",
        "help_owrx_port": "Port web d'OpenWebRX+.",
        "help_owrx_key": "Clau d'accés al panell d'OpenWebRX si el tens protegit.",
        "help_owrx_runtime": (
            "'native' fa servir el servei systemd instal·lat en aquest "
            "equip; 'docker' es connecta a un contenidor apart."
        ),
        "help_owrx_auto_open_on_start": "Obre la finestra de la cascada automàticament en arrencar la consola.",
        "help_owrx_follow_app_only": (
            "Si s'activa, OpenWebRX només canvia de banda/freqüència quan "
            "ho fa PoorSDR; ignora els canvis fets des del web d'OWRX."
        ),
        "help_owrx_sdr_hint": (
            "Nom del receptor a OpenWebRX (p. ex. 'RTL-SDR'). S'usa per "
            "triar el perfil en canviar de banda. Buit = autodetectar."
        ),
        "help_owrx_smeter_calibrated": "Fa servir una escala fixa (S9 al dBFS de sota) en lloc de l'autocalibratge. Només té sentit si has mesurat una referència real amb el guany de l'SDR fix (no 'auto').",
        "help_owrx_smeter_s9_dbfs": "El dBFS que informa OWRX exactament en un senyal de referència S9 conegut (p. ex. -73 dBm en HF), amb el guany de l'SDR fix. Només s'usa si 'S-metre calibrat' està activat.",
        "help_owrx_smeter_noise_floor_s": "Amb l'S-metre sense calibrar (per defecte), el soroll de fons/QRM detectat es mostra en aquesta unitat S, no en S0 — ajusta'l al QRM real de la teva estació, que no és igual arreu.",
        "help_owrx_band_profiles": 'Mapa banda→perfil, p. ex. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Minuts que un spot de DX segueix visible a la cascada abans de desaparèixer.",
        "help_spider_source": "D'on arriben els spots del clúster DX: un broker MQTT o un clúster Telnet clàssic.",
        "help_spider_mqtt_url": "Adreça del broker MQTT (p. ex. mqtt://host:1883) si la font és MQTT.",
        "help_spider_mqtt_topics": "Topics MQTT als quals subscriure's, separats per comes.",
        "help_spider_mqtt_user": "Usuari per autenticar-se al broker MQTT (buit si no cal).",
        "help_spider_mqtt_pass": "Contrasenya del broker MQTT (buit si no cal).",
        "help_spider_telnet_host": "Adreça Telnet del clúster DX (p. ex. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Port Telnet del clúster DX (normalment 7300).",
        "help_spider_telnet_call": "Indicatiu amb què t'identifiques en connectar al clúster Telnet.",
        "help_spider_telnet_pass": "Contrasenya del clúster Telnet (buit si no la demana).",
        "help_web_enabled": "Activa el servidor web remot per controlar la ràdio des d'un navegador.",
        "help_web_host": (
            "Adreça on escolta el servidor web. 0.0.0.0 = accessible des "
            "d'altres equips de la xarxa."
        ),
        "help_web_port": "Port TCP del servidor web.",
        "help_web_allow_wan": (
            "Permet l'accés des de fora de la xarxa local. Activa-ho només "
            "si saps què fas i uses HTTPS."
        ),
        "help_web_auto_https": "Genera i fa servir un certificat HTTPS automàticament en lloc d'HTTP pla.",
        "help_web_user": "Nom d'usuari per iniciar sessió al panell web.",
        "help_web_password": "Deixa-ho buit per conservar la contrasenya actual. Es desa salada i amb hash, mai en clar.",
        "help_ui_language": (
            "Idioma dels textos de la consola. (Encara en desenvolupament: "
            "avui només afecta alguns textos.)"
        ),
        "help_ui_theme": "Tema de color de la consola i la cascada.",
        "help_ui_display_mode": "Mode de recepció amb què arrenca la consola (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Macro {n} de {total}.",
        "help_autocall_name": "Etiqueta lliure per identificar el macro; no s'envia a la ràdio.",
        "help_autocall_audio": "Camí a l'arxiu d'àudio que es reprodueix en disparar el macro.",
        "help_autocall_pick": "Tria l'arxiu d'àudio del macro.",
        "help_autocall_reps": "Vegades que es repeteix l'àudio en disparar el macro.",
        "help_autocall_interval": "Segons de pausa entre cada repetició.",
        "help_autocall_button": "Macro que dispara el botó {n} de la consola.",
        "help_hotkeys_capture": "Fes clic i prem la tecla que vulguis assignar a aquesta acció. «Escape» l'esborra.",
        "help_hotkeys_clear": "Esborra la drecera assignada a aquesta acció.",
        "help_plugins_restart": "Els canvis s'apliquen en reiniciar PoorSDR.",
        "help_relays_enabled": "Activa el control dels relés de filtre per banda via WiFi (placa ESP).",
        "help_relays_url": "Adreça HTTP de la placa ESP que controla els relés (p. ex. http://192.168.1.50).",
        "help_relays_api_key": "Clau d'API de la placa ESP, si en té una configurada (buit si no cal).",
        "help_relays_timeout_ms": "Mil·lisegons d'espera abans de donar per fallida una petició a la placa ESP.",
        "help_relays_band_groups": 'Mapa banda→grup de relé, p. ex. {"40m": "40", "20m": "20"}.',
    },
    "gl": {
        "help_cat_port": "Dispositivo serie do cable CAT (p. ex. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' respecta Baudios/PTT por CAT de abaixo tal cal están. "
            "Un perfil con nome substitúeos: 'generic-ts480' = uSDX/(tr)uSDX "
            "de serie (38400, PTT por CAT); 'trusdx-115200' = (tr)uSDX "
            "firmware ≥2.00t (115200, aínda sen confirmar en hardware real)."
        ),
        "help_cat_baud": "Ignorado se o perfil de riba non é 'custom'.",
        "help_cat_control_mode": (
            "'direct' fala directamente coa radio polo porto CAT. 'hamlib' "
            "pasa por un rigctld externo xa en marcha (avanzado)."
        ),
        "help_cat_start_freq_hz": (
            "Frecuencia (en Hz) coa que arranca a consola se a radio non "
            "responde ao pedir o seu estado inicial."
        ),
        "help_cat_step_hz": "Paso de sintonía en Hz ao mover o VFO cos botóns ou o dial.",
        "help_rigctld_enabled": (
            "Activa o proxy rigctld: a ponte TCP que usan WSJT-X, N1MM, "
            "FreeDV e outros programas para controlar a radio."
        ),
        "help_rigctld_host": "Enderezo onde escoita o proxy rigctld. 127.0.0.1 = só este equipo.",
        "help_rigctld_port": "Porto TCP do proxy rigctld (o que se configura como 'rigctld' en WSJT-X/N1MM).",
        "help_n1m_enabled": "Emulador de radio Kenwood TS-480 por rede, para programas que non falan rigctld directamente.",
        "help_n1m_host": "Enderezo onde escoita o emulador TS-480.",
        "help_n1m_port": "Porto TCP do emulador TS-480.",
        "help_audio_rx_source": "De onde sae o audio de recepción: o SDR (OWRX) ou a radio física.",
        "help_audio_speaker_pc": "Saída de audio do PC onde escoitas a recepción.",
        "help_audio_mic_pc": "Entrada de audio do PC (micrófono) para transmitir por voz.",
        "help_audio_speaker_radio": "Entrada de audio desde a radio (o que a radio recibe, pasado ao PC).",
        "help_audio_mic_radio": "Saída de audio cara á radio (o que o PC envía para transmitir).",
        "help_owrx_enabled": "Activa a integración con OpenWebRX+ (backend, cascada, sintonía compartida).",
        "help_owrx_host": "Enderezo onde escoita OpenWebRX+.",
        "help_owrx_port": "Porto web de OpenWebRX+.",
        "help_owrx_key": "Clave de acceso ao panel de OpenWebRX se o tes protexido.",
        "help_owrx_runtime": (
            "'native' usa o servizo systemd instalado neste equipo; "
            "'docker' conéctase a un contedor á parte."
        ),
        "help_owrx_auto_open_on_start": "Abre a xanela da cascada automaticamente ao arrancar a consola.",
        "help_owrx_follow_app_only": (
            "Se se activa, OpenWebRX só cambia de banda/frecuencia cando o "
            "fai PoorSDR; ignora os cambios feitos desde a web de OWRX."
        ),
        "help_owrx_sdr_hint": (
            "Nome do receptor en OpenWebRX (p. ex. 'RTL-SDR'). Úsase para "
            "elixir o perfil ao cambiar de banda. Baleiro = autodetectar."
        ),
        "help_owrx_smeter_calibrated": "Usa unha escala fixa (S9 no dBFS de embaixo) no canto da autocalibración. Só ten sentido se mediches unha referencia real coa ganancia do SDR fixa (non 'auto').",
        "help_owrx_smeter_s9_dbfs": "O dBFS que reporta OWRX exactamente nunha sinal de referencia S9 coñecida (p. ex. -73 dBm en HF), coa ganancia do SDR fixa. Só se usa se 'S-metro calibrado' está activado.",
        "help_owrx_smeter_noise_floor_s": "Co S-metro sen calibrar (por defecto), o ruído de fondo/QRM detectado móstrase nesta unidade S, non en S0 — axústao ao QRM real da túa estación, que non é igual en todas partes.",
        "help_owrx_band_profiles": 'Mapa banda→perfil, p. ex. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Minutos que un spot de DX segue visible na cascada antes de desaparecer.",
        "help_spider_source": "De onde chegan os spots do clúster DX: un broker MQTT ou un clúster Telnet clásico.",
        "help_spider_mqtt_url": "Enderezo do broker MQTT (p. ex. mqtt://host:1883) se a fonte é MQTT.",
        "help_spider_mqtt_topics": "Topics MQTT aos que subscribirse, separados por comas.",
        "help_spider_mqtt_user": "Usuario para autenticarse no broker MQTT (baleiro se non fai falla).",
        "help_spider_mqtt_pass": "Contrasinal do broker MQTT (baleiro se non fai falla).",
        "help_spider_telnet_host": "Enderezo Telnet do clúster DX (p. ex. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Porto Telnet do clúster DX (normalmente 7300).",
        "help_spider_telnet_call": "Indicativo co que te identificas ao conectar ao clúster Telnet.",
        "help_spider_telnet_pass": "Contrasinal do clúster Telnet (baleiro se non o pide).",
        "help_web_enabled": "Activa o servidor web remoto para controlar a radio desde un navegador.",
        "help_web_host": (
            "Enderezo onde escoita o servidor web. 0.0.0.0 = accesible "
            "desde outros equipos da rede."
        ),
        "help_web_port": "Porto TCP do servidor web.",
        "help_web_allow_wan": (
            "Permite acceso desde fóra da túa rede local. Actívao só se "
            "sabes o que fas e usas HTTPS."
        ),
        "help_web_auto_https": "Xera e usa un certificado HTTPS automaticamente en vez de HTTP simple.",
        "help_web_user": "Nome de usuario para iniciar sesión no panel web.",
        "help_web_password": "Déixao baleiro para conservar o contrasinal actual. Gárdase salgado e con hash, nunca en claro.",
        "help_ui_language": (
            "Idioma dos textos da consola. (Aínda en desenvolvemento: hoxe "
            "só afecta a algúns textos.)"
        ),
        "help_ui_theme": "Tema de cor da consola e a cascada.",
        "help_ui_display_mode": "Modo de recepción co que arranca a consola (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Macro {n} de {total}.",
        "help_autocall_name": "Etiqueta libre para identificar o macro; non se envía á radio.",
        "help_autocall_audio": "Ruta ao ficheiro de audio que se reproduce ao disparar o macro.",
        "help_autocall_pick": "Elixir o ficheiro de audio do macro.",
        "help_autocall_reps": "Veces que se repite o audio ao disparar o macro.",
        "help_autocall_interval": "Segundos de pausa entre cada repetición.",
        "help_autocall_button": "Macro que dispara o botón {n} da consola.",
        "help_hotkeys_capture": "Fai clic e preme a tecla que queiras asignar a esta acción. «Escape» bórraa.",
        "help_hotkeys_clear": "Borra o atallo asignado a esta acción.",
        "help_plugins_restart": "Os cambios aplícanse ao reiniciar PoorSDR.",
        "help_relays_enabled": "Activa o control dos relés de filtro por banda vía WiFi (placa ESP).",
        "help_relays_url": "Enderezo HTTP da placa ESP que controla os relés (p. ex. http://192.168.1.50).",
        "help_relays_api_key": "Clave de API da placa ESP, se a ten configurada (baleiro se non fai falla).",
        "help_relays_timeout_ms": "Milisegundos de espera antes de dar por fallida unha petición á placa ESP.",
        "help_relays_band_groups": 'Mapa banda→grupo de relé, p. ex. {"40m": "40", "20m": "20"}.',
    },
    "eu": {
        "help_cat_port": "CAT kablearen gailu seriea (adib. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' aukerak beheko Baud/PTT CAT bidez daudenak bezala "
            "uzten ditu. Izendun profil batek ordezkatzen ditu: "
            "'generic-ts480' = uSDX/(tr)uSDX jatorrizkoa (38400, PTT CAT "
            "bidez); 'trusdx-115200' = (tr)uSDX firmware ≥2.00t (115200, "
            "oraindik hardware errealean baieztatu gabe)."
        ),
        "help_cat_baud": "Ez ikusia egiten zaio goiko profila 'custom' ez bada.",
        "help_cat_control_mode": (
            "'direct' zuzenean hitz egiten dio irratiari CAT atakaren "
            "bidez. 'hamlib' martxan dagoen kanpoko rigctld baten bidez "
            "doa (aurreratua)."
        ),
        "help_cat_start_freq_hz": (
            "Kontsola abiarazten den maiztasuna (Hz), irratiak hasierako "
            "egoera eskatzean erantzuten ez badu."
        ),
        "help_cat_step_hz": "Sintonia urratsa Hz-tan, VFOa botoiekin edo diskoarekin mugitzean.",
        "help_rigctld_enabled": (
            "rigctld proxya aktibatzen du: WSJT-X, N1MM, FreeDV eta beste "
            "programa batzuek irratia kontrolatzeko erabiltzen duten TCP "
            "zubia."
        ),
        "help_rigctld_host": "rigctld proxyak entzuten duen helbidea. 127.0.0.1 = ekipo hau bakarrik.",
        "help_rigctld_port": "rigctld proxyaren TCP ataka (WSJT-X/N1MM-n 'rigctld' gisa ezarritakoa).",
        "help_n1m_enabled": "Kenwood TS-480 sareko emuladorea, rigctld zuzenean hitz egiten ez duten programentzat.",
        "help_n1m_host": "TS-480 emuladoreak entzuten duen helbidea.",
        "help_n1m_port": "TS-480 emuladorearen TCP ataka.",
        "help_audio_rx_source": "Harrera audioa nondik datorren: SDR-a (OWRX) edo irrati fisikoa.",
        "help_audio_speaker_pc": "PCko audio irteera, harrera entzuteko.",
        "help_audio_mic_pc": "PCko audio sarrera (mikrofonoa) ahotsez transmititzeko.",
        "help_audio_speaker_radio": "Irratitik datorren audio sarrera (irratiak jasotzen duena, PCra pasatuta).",
        "help_audio_mic_radio": "Irratirako audio irteera (PCk transmititzeko bidaltzen duena).",
        "help_owrx_enabled": "OpenWebRX+ integrazioa aktibatzen du (backend, urjauzia, sintonia partekatua).",
        "help_owrx_host": "OpenWebRX+k entzuten duen helbidea.",
        "help_owrx_port": "OpenWebRX+ren web ataka.",
        "help_owrx_key": "OpenWebRX panelerako sarbide gakoa, babestuta baldin badago.",
        "help_owrx_runtime": (
            "'native' ekipo honetan instalatutako systemd zerbitzua "
            "erabiltzen du; 'docker' bereizitako edukiontzi batera "
            "konektatzen da."
        ),
        "help_owrx_auto_open_on_start": "Urjauziaren leihoa automatikoki irekitzen du kontsola abiaraztean.",
        "help_owrx_follow_app_only": (
            "Aktibatuta badago, OpenWebRX-k banda/maiztasuna PoorSDR-k "
            "egiten duenean bakarrik aldatzen du; OWRX weberako aldaketei "
            "ez ikusia egiten die."
        ),
        "help_owrx_sdr_hint": (
            "OpenWebRX-eko hargailuaren izena (adib. 'RTL-SDR'). Banda "
            "aldatzean profila aukeratzeko erabiltzen da. Hutsik = "
            "automatikoki detektatu."
        ),
        "help_owrx_smeter_calibrated": "Autokalibrazioaren ordez eskala finko bat erabiltzen du (S9 azpiko dBFSan). Zentzua du soilik SDRren irabazia finkoa dagoenean (ez 'auto') erreferentzia erreal bat neurtu baduzu.",
        "help_owrx_smeter_s9_dbfs": "OWRXk S9 erreferentzia-seinale ezagun batean (adib. -73 dBm HFan) ematen duen dBFSa, SDRren irabazia finkoarekin. 'S-metroa kalibratuta' aktibatuta dagoenean bakarrik erabiltzen da.",
        "help_owrx_smeter_noise_floor_s": "S-metroa kalibratu gabe dagoela (lehenetsia), atzemandako zarata/QRM S unitate honetan erakusten da, ez S0-n — ezarri zure estazioaren benetako QRM-ra, ez baita berdina toki guztietan.",
        "help_owrx_band_profiles": 'Banda→profil mapa, adib. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "DX spot bat urjauzian ikusgai jarraitzen duen minutuak, desagertu aurretik.",
        "help_spider_source": "DX cluster-eko spotak nondik datozen: MQTT broker bat edo Telnet cluster klasiko bat.",
        "help_spider_mqtt_url": "MQTT brokerraren helbidea (adib. mqtt://host:1883), iturria MQTT bada.",
        "help_spider_mqtt_topics": "Harpidetzeko MQTT gaiak, komaz bereizita.",
        "help_spider_mqtt_user": "MQTT brokerrean autentifikatzeko erabiltzailea (hutsik behar ez bada).",
        "help_spider_mqtt_pass": "MQTT brokerraren pasahitza (hutsik behar ez bada).",
        "help_spider_telnet_host": "DX cluster-aren Telnet helbidea (adib. dxc.ea7ur.com).",
        "help_spider_telnet_port": "DX cluster-aren Telnet ataka (normalean 7300).",
        "help_spider_telnet_call": "Telnet cluster-era konektatzean identifikatzeko deitura.",
        "help_spider_telnet_pass": "Telnet cluster-aren pasahitza (hutsik eskatzen ez badu).",
        "help_web_enabled": "Urruneko web zerbitzaria aktibatzen du, irratia arakatzaile batetik kontrolatzeko.",
        "help_web_host": (
            "Web zerbitzariak entzuten duen helbidea. 0.0.0.0 = sareko "
            "beste ekipoetatik eskuragarri."
        ),
        "help_web_port": "Web zerbitzariaren TCP ataka.",
        "help_web_allow_wan": (
            "Sare lokaletik kanpoko sarbidea baimentzen du. Aktibatu zer "
            "egiten ari zaren jakinez gero bakarrik, eta HTTPS erabiliz."
        ),
        "help_web_auto_https": "HTTPS ziurtagiri bat automatikoki sortu eta erabiltzen du, HTTP soilaren ordez.",
        "help_web_user": "Web panelean saioa hasteko erabiltzaile izena.",
        "help_web_password": "Utzi hutsik uneko pasahitza mantentzeko. Gatzatuta eta hash eginda gordetzen da, inoiz ez testu arruntean.",
        "help_ui_language": (
            "Kontsolaren testuen hizkuntza. (Oraindik garapenean: gaur "
            "egun testu batzuei bakarrik eragiten die.)"
        ),
        "help_ui_theme": "Kontsolaren eta urjauziaren kolore gaia.",
        "help_ui_display_mode": "Kontsola abiarazten den harrera modua (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "{n}/{total} makroa.",
        "help_autocall_name": "Makroa identifikatzeko etiketa librea; ez zaio irratiari bidaltzen.",
        "help_autocall_audio": "Makroa abiaraztean erreproduzitzen den audio fitxategiaren bidea.",
        "help_autocall_pick": "Aukeratu makroaren audio fitxategia.",
        "help_autocall_reps": "Makroa abiaraztean audioa zenbat aldiz errepikatzen den.",
        "help_autocall_interval": "Errepikapen bakoitzaren arteko pausaren segundoak.",
        "help_autocall_button": "Kontsolaren {n} botoiak abiarazten duen makroa.",
        "help_hotkeys_capture": "Egin klik eta ekintza honi esleitu nahi diozun tekla sakatu. «Escape»-k ezabatzen du.",
        "help_hotkeys_clear": "Ekintza honi esleitutako lasterbidea ezabatzen du.",
        "help_plugins_restart": "Aldaketak PoorSDR berrabiaraztean aplikatzen dira.",
        "help_relays_enabled": "Bandaka iragazki-erreleen kontrola aktibatzen du WiFi bidez (ESP plaka).",
        "help_relays_url": "Erreleak kontrolatzen dituen ESP plakaren HTTP helbidea (adib. http://192.168.1.50).",
        "help_relays_api_key": "ESP plakaren API gakoa, konfiguratuta badu (hutsik behar ez bada).",
        "help_relays_timeout_ms": "ESP plakarako eskaera bat huts egindakotzat jo aurretik itxaroteko milisegundoak.",
        "help_relays_band_groups": 'Banda→errele talde mapa, adib. {"40m": "40", "20m": "20"}.',
    },
    "pl": {
        "help_cat_port": "Urządzenie szeregowe kabla CAT (np. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' zachowuje Baud/PTT przez CAT poniżej bez zmian. "
            "Nazwany profil je zastępuje: 'generic-ts480' = domyślne "
            "uSDX/(tr)uSDX (38400, PTT przez CAT); 'trusdx-115200' = "
            "(tr)uSDX firmware ≥2.00t (115200, jeszcze niepotwierdzone na "
            "prawdziwym sprzęcie)."
        ),
        "help_cat_baud": "Ignorowane, jeśli profil powyżej nie jest 'custom'.",
        "help_cat_control_mode": (
            "'direct' rozmawia z radiem bezpośrednio przez port CAT. "
            "'hamlib' korzysta z już uruchomionego zewnętrznego rigctld "
            "(zaawansowane)."
        ),
        "help_cat_start_freq_hz": (
            "Częstotliwość (w Hz), z jaką startuje konsola, jeśli radio nie "
            "odpowiada na zapytanie o stan początkowy."
        ),
        "help_cat_step_hz": "Krok strojenia w Hz przy przesuwaniu VFO przyciskami lub pokrętłem.",
        "help_rigctld_enabled": (
            "Włącza proxy rigctld: most TCP, którego używają WSJT-X, N1MM, "
            "FreeDV i inne programy do sterowania radiem."
        ),
        "help_rigctld_host": "Adres, na którym nasłuchuje proxy rigctld. 127.0.0.1 = tylko ten komputer.",
        "help_rigctld_port": "Port TCP proxy rigctld (ten ustawiany jako 'rigctld' w WSJT-X/N1MM).",
        "help_n1m_enabled": "Emulator sieciowy Kenwood TS-480, dla programów, które nie mówią bezpośrednio rigctld.",
        "help_n1m_host": "Adres, na którym nasłuchuje emulator TS-480.",
        "help_n1m_port": "Port TCP emulatora TS-480.",
        "help_audio_rx_source": "Skąd pochodzi dźwięk odbioru: SDR (OWRX) czy fizyczne radio.",
        "help_audio_speaker_pc": "Wyjście audio PC, na którym słychać odbiór.",
        "help_audio_mic_pc": "Wejście audio PC (mikrofon) do nadawania głosem.",
        "help_audio_speaker_radio": "Wejście audio z radia (to, co radio odbiera, przekazywane do PC).",
        "help_audio_mic_radio": "Wyjście audio do radia (to, co PC wysyła do nadawania).",
        "help_owrx_enabled": "Włącza integrację z OpenWebRX+ (backend, wodospad, współdzielone strojenie).",
        "help_owrx_host": "Adres, na którym nasłuchuje OpenWebRX+.",
        "help_owrx_port": "Port web OpenWebRX+.",
        "help_owrx_key": "Klucz dostępu do panelu OpenWebRX, jeśli jest chroniony.",
        "help_owrx_runtime": (
            "'native' używa usługi systemd zainstalowanej na tym "
            "komputerze; 'docker' łączy się z osobnym kontenerem."
        ),
        "help_owrx_auto_open_on_start": "Automatycznie otwiera okno wodospadu przy starcie konsoli.",
        "help_owrx_follow_app_only": (
            "Gdy włączone, OpenWebRX zmienia pasmo/częstotliwość tylko "
            "wtedy, gdy robi to PoorSDR; ignoruje zmiany z panelu web OWRX."
        ),
        "help_owrx_sdr_hint": (
            "Nazwa odbiornika w OpenWebRX (np. 'RTL-SDR'). Używana do "
            "wyboru profilu przy zmianie pasma. Puste = automatyczne "
            "wykrywanie."
        ),
        "help_owrx_smeter_calibrated": "Używa stałej skali (S9 przy podanym dBFS) zamiast autokalibracji. Ma sens tylko jeśli zmierzono prawdziwy sygnał odniesienia przy stałym wzmocnieniu SDR (nie 'auto').",
        "help_owrx_smeter_s9_dbfs": "Wartość dBFS, którą OWRX zgłasza dokładnie przy znanym sygnale odniesienia S9 (np. -73 dBm w HF), przy stałym wzmocnieniu SDR. Używane tylko gdy włączony jest 'Skalibrowany S-metr'.",
        "help_owrx_smeter_noise_floor_s": "Przy nieskalibrowanym S-metrze (domyślnie) wykryty szum tła/QRM jest pokazywany na tej jednostce S, nie na S0 — dostosuj do rzeczywistego QRM twojej stacji, który nie jest wszędzie taki sam.",
        "help_owrx_band_profiles": 'Mapa pasmo→profil, np. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Minuty, przez które spot DX pozostaje widoczny na wodospadzie, zanim zniknie.",
        "help_spider_source": "Skąd pochodzą spoty klastra DX: broker MQTT czy klasyczny klaster Telnet.",
        "help_spider_mqtt_url": "Adres brokera MQTT (np. mqtt://host:1883), jeśli źródłem jest MQTT.",
        "help_spider_mqtt_topics": "Tematy MQTT do subskrypcji, oddzielone przecinkami.",
        "help_spider_mqtt_user": "Użytkownik do uwierzytelnienia w brokerze MQTT (puste, jeśli niepotrzebne).",
        "help_spider_mqtt_pass": "Hasło brokera MQTT (puste, jeśli niepotrzebne).",
        "help_spider_telnet_host": "Adres Telnet klastra DX (np. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Port Telnet klastra DX (zwykle 7300).",
        "help_spider_telnet_call": "Znak wywoławczy, którym identyfikujesz się przy łączeniu z klastrem Telnet.",
        "help_spider_telnet_pass": "Hasło klastra Telnet (puste, jeśli nie jest wymagane).",
        "help_web_enabled": "Włącza zdalny serwer web do sterowania radiem z przeglądarki.",
        "help_web_host": (
            "Adres, na którym nasłuchuje serwer web. 0.0.0.0 = dostępny z "
            "innych komputerów w sieci."
        ),
        "help_web_port": "Port TCP serwera web.",
        "help_web_allow_wan": (
            "Zezwala na dostęp spoza sieci lokalnej. Włącz tylko, jeśli "
            "wiesz, co robisz, i używasz HTTPS."
        ),
        "help_web_auto_https": "Automatycznie generuje i używa certyfikatu HTTPS zamiast zwykłego HTTP.",
        "help_web_user": "Nazwa użytkownika do logowania w panelu web.",
        "help_web_password": "Zostaw puste, aby zachować obecne hasło. Zapisywane solone i hashowane, nigdy jawnie.",
        "help_ui_language": (
            "Język tekstów konsoli. (Wciąż w opracowaniu: obecnie dotyczy "
            "tylko niektórych tekstów.)"
        ),
        "help_ui_theme": "Motyw kolorystyczny konsoli i wodospadu.",
        "help_ui_display_mode": "Tryb odbioru, z którym startuje konsola (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Makro {n} z {total}.",
        "help_autocall_name": "Dowolna etykieta do identyfikacji makra; nie jest wysyłana do radia.",
        "help_autocall_audio": "Ścieżka do pliku audio odtwarzanego po uruchomieniu makra.",
        "help_autocall_pick": "Wybierz plik audio makra.",
        "help_autocall_reps": "Ile razy powtarza się audio po uruchomieniu makra.",
        "help_autocall_interval": "Sekundy przerwy między każdym powtórzeniem.",
        "help_autocall_button": "Makro uruchamiane przyciskiem {n} konsoli.",
        "help_hotkeys_capture": "Kliknij, a potem naciśnij klawisz, który chcesz przypisać do tej akcji. „Escape” go czyści.",
        "help_hotkeys_clear": "Czyści skrót przypisany do tej akcji.",
        "help_plugins_restart": "Zmiany zostaną zastosowane po ponownym uruchomieniu PoorSDR.",
        "help_relays_enabled": "Włącza sterowanie przekaźnikami filtrów pasmowych przez WiFi (płytka ESP).",
        "help_relays_url": "Adres HTTP płytki ESP sterującej przekaźnikami (np. http://192.168.1.50).",
        "help_relays_api_key": "Klucz API płytki ESP, jeśli jest skonfigurowany (puste, jeśli niepotrzebny).",
        "help_relays_timeout_ms": "Milisekundy oczekiwania, zanim żądanie do płytki ESP zostanie uznane za nieudane.",
        "help_relays_band_groups": 'Mapa pasmo→grupa przekaźnika, np. {"40m": "40", "20m": "20"}.',
    },
    "ru": {
        "help_cat_port": "Последовательное устройство кабеля CAT (напр. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' сохраняет скорость/PTT по CAT ниже без изменений. "
            "Именованный профиль их заменяет: 'generic-ts480' — стандартный "
            "uSDX/(tr)uSDX (38400, PTT по CAT); 'trusdx-115200' — прошивка "
            "(tr)uSDX ≥2.00t (115200, ещё не подтверждено на реальном "
            "оборудовании)."
        ),
        "help_cat_baud": "Игнорируется, если профиль выше не 'custom'.",
        "help_cat_control_mode": (
            "'direct' общается с радио напрямую через порт CAT. 'hamlib' "
            "использует уже запущенный внешний rigctld (для опытных)."
        ),
        "help_cat_start_freq_hz": (
            "Частота (в Гц), с которой запускается консоль, если радио не "
            "отвечает на запрос начального состояния."
        ),
        "help_cat_step_hz": "Шаг настройки в Гц при перемещении VFO кнопками или диском.",
        "help_rigctld_enabled": (
            "Включает прокси rigctld: TCP-мост, который используют WSJT-X, "
            "N1MM, FreeDV и другие программы для управления радио."
        ),
        "help_rigctld_host": "Адрес, на котором слушает прокси rigctld. 127.0.0.1 — только этот компьютер.",
        "help_rigctld_port": "TCP-порт прокси rigctld (тот, что указывается как 'rigctld' в WSJT-X/N1MM).",
        "help_n1m_enabled": "Сетевой эмулятор Kenwood TS-480 для программ, не понимающих rigctld напрямую.",
        "help_n1m_host": "Адрес, на котором слушает эмулятор TS-480.",
        "help_n1m_port": "TCP-порт эмулятора TS-480.",
        "help_audio_rx_source": "Откуда берётся звук приёма: SDR (OWRX) или физическое радио.",
        "help_audio_speaker_pc": "Аудиовыход ПК, на котором слышен приём.",
        "help_audio_mic_pc": "Аудиовход ПК (микрофон) для передачи голосом.",
        "help_audio_speaker_radio": "Аудиовход от радио (то, что радио принимает, передаётся на ПК).",
        "help_audio_mic_radio": "Аудиовыход на радио (то, что ПК отправляет для передачи).",
        "help_owrx_enabled": "Включает интеграцию с OpenWebRX+ (бэкенд, водопад, общая настройка частоты).",
        "help_owrx_host": "Адрес, на котором слушает OpenWebRX+.",
        "help_owrx_port": "Веб-порт OpenWebRX+.",
        "help_owrx_key": "Ключ доступа к панели OpenWebRX, если она защищена.",
        "help_owrx_runtime": (
            "'native' использует службу systemd, установленную на этом "
            "компьютере; 'docker' подключается к отдельному контейнеру."
        ),
        "help_owrx_auto_open_on_start": "Автоматически открывает окно водопада при запуске консоли.",
        "help_owrx_follow_app_only": (
            "Если включено, OpenWebRX меняет диапазон/частоту только вслед "
            "за PoorSDR; изменения из веб-интерфейса OWRX игнорируются."
        ),
        "help_owrx_sdr_hint": (
            "Имя приёмника в OpenWebRX (напр. 'RTL-SDR'). Используется для "
            "выбора профиля при смене диапазона. Пусто — автоопределение."
        ),
        "help_owrx_smeter_calibrated": "Использует фиксированную шкалу (S9 при указанном dBFS) вместо автокалибровки. Имеет смысл только если вы измерили реальный опорный сигнал при фиксированном усилении SDR (не 'авто').",
        "help_owrx_smeter_s9_dbfs": "Уровень dBFS, который OWRX показывает точно на известном опорном сигнале S9 (например, -73 дБм на КВ), при фиксированном усилении SDR. Используется только если включён 'S-метр откалиброван'.",
        "help_owrx_smeter_noise_floor_s": "При некалиброванном S-метре (по умолчанию) обнаруженный фоновый шум/QRM отображается на этой единице S, а не на S0 — настройте под реальный QRM вашей станции, который не одинаков везде.",
        "help_owrx_band_profiles": 'Карта диапазон→профиль, напр. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Минуты, в течение которых DX-спот виден на водопаде, прежде чем исчезнуть.",
        "help_spider_source": "Откуда берутся споты DX-кластера: брокер MQTT или классический Telnet-кластер.",
        "help_spider_mqtt_url": "Адрес брокера MQTT (напр. mqtt://host:1883), если источник — MQTT.",
        "help_spider_mqtt_topics": "Темы MQTT для подписки, через запятую.",
        "help_spider_mqtt_user": "Имя пользователя для аутентификации на брокере MQTT (пусто, если не нужно).",
        "help_spider_mqtt_pass": "Пароль брокера MQTT (пусто, если не нужен).",
        "help_spider_telnet_host": "Telnet-адрес DX-кластера (напр. dxc.ea7ur.com).",
        "help_spider_telnet_port": "Telnet-порт DX-кластера (обычно 7300).",
        "help_spider_telnet_call": "Позывной, которым вы представляетесь при подключении к Telnet-кластеру.",
        "help_spider_telnet_pass": "Пароль Telnet-кластера (пусто, если не запрашивается).",
        "help_web_enabled": "Включает удалённый веб-сервер для управления радио из браузера.",
        "help_web_host": (
            "Адрес, на котором слушает веб-сервер. 0.0.0.0 — доступен с "
            "других компьютеров сети."
        ),
        "help_web_port": "TCP-порт веб-сервера.",
        "help_web_allow_wan": (
            "Разрешает доступ извне локальной сети. Включайте, только если "
            "понимаете риски и используете HTTPS."
        ),
        "help_web_auto_https": "Автоматически создаёт и использует сертификат HTTPS вместо обычного HTTP.",
        "help_web_user": "Имя пользователя для входа в веб-панель.",
        "help_web_password": "Оставьте пустым, чтобы сохранить текущий пароль. Хранится с солью и хешем, никогда в открытом виде.",
        "help_ui_language": (
            "Язык текстов консоли. (Пока в разработке: сегодня влияет "
            "только на часть текстов.)"
        ),
        "help_ui_theme": "Цветовая тема консоли и водопада.",
        "help_ui_display_mode": "Режим приёма, с которым запускается консоль (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Макрос {n} из {total}.",
        "help_autocall_name": "Произвольная метка для идентификации макроса; не отправляется на радио.",
        "help_autocall_audio": "Путь к аудиофайлу, который проигрывается при срабатывании макроса.",
        "help_autocall_pick": "Выбрать аудиофайл макроса.",
        "help_autocall_reps": "Сколько раз повторяется аудио при срабатывании макроса.",
        "help_autocall_interval": "Секунды паузы между повторениями.",
        "help_autocall_button": "Макрос, запускаемый кнопкой {n} консоли.",
        "help_hotkeys_capture": "Нажмите, затем нажмите клавишу, которую хотите назначить этому действию. «Escape» очищает.",
        "help_hotkeys_clear": "Очищает горячую клавишу, назначенную этому действию.",
        "help_plugins_restart": "Изменения применяются при перезапуске PoorSDR.",
        "help_relays_enabled": "Включает управление реле полосовых фильтров по WiFi (плата ESP).",
        "help_relays_url": "HTTP-адрес платы ESP, управляющей реле (напр. http://192.168.1.50).",
        "help_relays_api_key": "API-ключ платы ESP, если он настроен (пусто, если не нужен).",
        "help_relays_timeout_ms": "Миллисекунды ожидания, прежде чем запрос к плате ESP считается неудачным.",
        "help_relays_band_groups": 'Карта диапазон→группа реле, напр. {"40m": "40", "20m": "20"}.',
    },
    "tr": {
        "help_cat_port": "CAT kablosunun seri aygıtı (örn. /dev/ttyUSB0).",
        "help_cat_rig_profile": (
            "'custom' aşağıdaki Baud/CAT üzerinden PTT değerlerini olduğu "
            "gibi kullanır. Adlandırılmış bir profil bunları değiştirir: "
            "'generic-ts480' = standart uSDX/(tr)uSDX (38400, CAT üzerinden "
            "PTT); 'trusdx-115200' = (tr)uSDX firmware ≥2.00t (115200, "
            "gerçek donanımda henüz doğrulanmadı)."
        ),
        "help_cat_baud": "Yukarıdaki profil 'custom' değilse yok sayılır.",
        "help_cat_control_mode": (
            "'direct' telsizle doğrudan CAT portu üzerinden konuşur. "
            "'hamlib' zaten çalışan harici bir rigctld üzerinden gider "
            "(ileri düzey)."
        ),
        "help_cat_start_freq_hz": (
            "Telsiz başlangıç durumunu sormaya yanıt vermezse konsolun "
            "başladığı frekans (Hz)."
        ),
        "help_cat_step_hz": "VFO'yu düğmelerle veya kadranla hareket ettirirken Hz cinsinden ayar adımı.",
        "help_rigctld_enabled": (
            "rigctld proxy'sini etkinleştirir: WSJT-X, N1MM, FreeDV ve "
            "diğer programların telsizi kontrol etmek için kullandığı TCP "
            "köprüsü."
        ),
        "help_rigctld_host": "rigctld proxy'sinin dinlediği adres. 127.0.0.1 = yalnızca bu bilgisayar.",
        "help_rigctld_port": "rigctld proxy'sinin TCP portu (WSJT-X/N1MM'de 'rigctld' olarak ayarlanan).",
        "help_n1m_enabled": "rigctld ile doğrudan konuşmayan programlar için Kenwood TS-480 ağ emülatörü.",
        "help_n1m_host": "TS-480 emülatörünün dinlediği adres.",
        "help_n1m_port": "TS-480 emülatörünün TCP portu.",
        "help_audio_rx_source": "Alım sesinin nereden geldiği: SDR (OWRX) veya fiziksel telsiz.",
        "help_audio_speaker_pc": "Alımı dinlediğiniz PC ses çıkışı.",
        "help_audio_mic_pc": "Sesle verici için PC ses girişi (mikrofon).",
        "help_audio_speaker_radio": "Telsizden gelen ses girişi (telsizin aldığı, PC'ye aktarılan).",
        "help_audio_mic_radio": "Telsize giden ses çıkışı (PC'nin verici için gönderdiği).",
        "help_owrx_enabled": "OpenWebRX+ entegrasyonunu etkinleştirir (arka uç, şelale, ortak ayar).",
        "help_owrx_host": "OpenWebRX+'in dinlediği adres.",
        "help_owrx_port": "OpenWebRX+ web portu.",
        "help_owrx_key": "Korumalıysa OpenWebRX paneline erişim anahtarı.",
        "help_owrx_runtime": (
            "'native' bu bilgisayara kurulu systemd hizmetini kullanır; "
            "'docker' ayrı bir konteynere bağlanır."
        ),
        "help_owrx_auto_open_on_start": "Konsol başlarken şelale penceresini otomatik açar.",
        "help_owrx_follow_app_only": (
            "Etkinse, OpenWebRX bant/frekansı yalnızca PoorSDR "
            "değiştirdiğinde değiştirir; OWRX webinden yapılan "
            "değişiklikleri yok sayar."
        ),
        "help_owrx_sdr_hint": (
            "OpenWebRX'teki alıcı adı (örn. 'RTL-SDR'). Bant değişiminde "
            "profil seçmek için kullanılır. Boş = otomatik algıla."
        ),
        "help_owrx_smeter_calibrated": "Otomatik kalibrasyon yerine sabit bir ölçek kullanır (aşağıdaki dBFS'de S9). Yalnızca SDR kazancı sabitken (otomatik değil) gerçek bir referans ölçtüyseniz anlamlıdır.",
        "help_owrx_smeter_s9_dbfs": "OWRX'in bilinen bir S9 referans sinyalinde (örn. HF'de -73 dBm) bildirdiği dBFS, SDR kazancı sabitken. Yalnızca 'Kalibreli S-metre' etkinse kullanılır.",
        "help_owrx_smeter_noise_floor_s": "Kalibre edilmemiş S-metre ile (varsayılan), algılanan gürültü tabanı/QRM S0'da değil bu S biriminde gösterilir — bunu istasyonunuzun gerçek ortam QRM'sine göre ayarlayın, her yerde aynı değildir.",
        "help_owrx_band_profiles": 'Bant→profil eşlemesi, örn. {"40m": "RTL 40m", "20m": "RTL 20m"}.',
        "help_spots_retention_min": "Bir DX spotunun kaybolmadan önce şelalede görünür kaldığı dakika sayısı.",
        "help_spider_source": "DX küme spotlarının nereden geldiği: bir MQTT broker'ı veya klasik bir Telnet kümesi.",
        "help_spider_mqtt_url": "Kaynak MQTT ise MQTT broker adresi (örn. mqtt://host:1883).",
        "help_spider_mqtt_topics": "Abone olunacak MQTT konuları, virgülle ayrılmış.",
        "help_spider_mqtt_user": "MQTT broker'ında kimlik doğrulama için kullanıcı adı (gerekmiyorsa boş).",
        "help_spider_mqtt_pass": "MQTT broker şifresi (gerekmiyorsa boş).",
        "help_spider_telnet_host": "DX kümesinin Telnet adresi (örn. dxc.ea7ur.com).",
        "help_spider_telnet_port": "DX kümesinin Telnet portu (genellikle 7300).",
        "help_spider_telnet_call": "Telnet kümesine bağlanırken kimliğinizi belirttiğiniz çağrı işareti.",
        "help_spider_telnet_pass": "Telnet kümesi şifresi (istenmiyorsa boş).",
        "help_web_enabled": "Telsizi bir tarayıcıdan kontrol etmek için uzak web sunucusunu etkinleştirir.",
        "help_web_host": (
            "Web sunucusunun dinlediği adres. 0.0.0.0 = ağdaki diğer "
            "bilgisayarlardan erişilebilir."
        ),
        "help_web_port": "Web sunucusunun TCP portu.",
        "help_web_allow_wan": (
            "Yerel ağ dışından erişime izin verir. Yalnızca ne "
            "yaptığınızı biliyorsanız ve HTTPS kullanıyorsanız "
            "etkinleştirin."
        ),
        "help_web_auto_https": "Düz HTTP yerine otomatik olarak bir HTTPS sertifikası oluşturur ve kullanır.",
        "help_web_user": "Web paneline giriş için kullanıcı adı.",
        "help_web_password": "Mevcut şifreyi korumak için boş bırakın. Tuzlanmış ve hash'lenmiş olarak saklanır, asla düz metin olarak değil.",
        "help_ui_language": (
            "Konsol metinlerinin dili. (Hâlâ geliştiriliyor: bugün "
            "yalnızca bazı metinleri etkiler.)"
        ),
        "help_ui_theme": "Konsol ve şelalenin renk teması.",
        "help_ui_display_mode": "Konsolun başladığı alım modu (LSB/USB/CW/FM/AM/DIGU).",
        "help_autocall_index": "Makro {n}/{total}.",
        "help_autocall_name": "Makroyu tanımlamak için serbest etiket; telsize gönderilmez.",
        "help_autocall_audio": "Makro tetiklendiğinde çalınan ses dosyasının yolu.",
        "help_autocall_pick": "Makronun ses dosyasını seçin.",
        "help_autocall_reps": "Makro tetiklendiğinde sesin kaç kez tekrarlanacağı.",
        "help_autocall_interval": "Her tekrar arasındaki duraklama saniyesi.",
        "help_autocall_button": "Konsolun {n} düğmesiyle tetiklenen makro.",
        "help_hotkeys_capture": "Tıklayın, ardından bu eyleme atamak istediğiniz tuşa basın. 'Escape' temizler.",
        "help_hotkeys_clear": "Bu eyleme atanan kısayolu temizler.",
        "help_plugins_restart": "Değişiklikler PoorSDR yeniden başlatıldığında uygulanır.",
        "help_relays_enabled": "WiFi üzerinden bant filtresi röle kontrolünü etkinleştirir (ESP kart).",
        "help_relays_url": "Röleleri kontrol eden ESP kartının HTTP adresi (örn. http://192.168.1.50).",
        "help_relays_api_key": "ESP kartının API anahtarı, ayarlıysa (gerekmiyorsa boş).",
        "help_relays_timeout_ms": "ESP kartına yapılan bir isteğin başarısız sayılmadan önce beklenecek milisaniye.",
        "help_relays_band_groups": 'Bant→röle grubu eşlemesi, örn. {"40m": "40", "20m": "20"}.',
    },
}


def field_help(key: str, lang: str = DEFAULT_LANG, **kwargs: object) -> str:
    """Texto de ayuda de ``key`` en ``lang``; cae a español si falta.

    Vacío si ``key`` está vacía o no existe en ningún idioma. Si el texto
    resuelto lleva plantillas (``{n}``...), se aplican ``kwargs`` con
    ``str.format``.
    """
    if not key:
        return ""
    table = HELP.get(lang, {})
    text = table.get(key)
    if text is None:
        text = HELP.get(DEFAULT_LANG, {}).get(key, "")
    if not text:
        return ""
    return text.format(**kwargs) if kwargs else text


__all__ = ["DEFAULT_LANG", "HELP", "field_help"]
