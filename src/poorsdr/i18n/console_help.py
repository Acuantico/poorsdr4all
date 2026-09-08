"""Ayuda contextual (tooltips) de la consola principal, por idioma.

Independiente de ``strings.idiomas`` y de ``settings_help``: la consola es
una ventana de tamaño fijo (620x760) que reproduce un faceplate de radio, con
botones de ancho fijo en caracteres. Muchas de sus etiquetas (Ajustes, Mem,
Spots, WEB ON/OFF, Digi ON/OFF, PTT, TX, ANR, MODE, BAND, MHz, kHz, CH -/+...)
se dejan tal cual en todos los idiomas para no romper ese diseño — igual que
ya hacía la propia consola en español con PTT/TX/MHz/MODE/BAND. Este módulo
añade lo que esas etiquetas cortas no pueden decir por sí solas: un tooltip
traducido a los 12 idiomas para cada control, igual que ``settings_help``.

Mismo mecanismo de resolución que :func:`poorsdr.i18n.t` — cae a español si
falta la clave o el idioma. Las claves con ``{n}`` son plantillas: acepta
``**kwargs`` y aplica ``.format(**kwargs)`` sobre el texto resuelto.
"""

from __future__ import annotations

DEFAULT_LANG = "es"

HELP: dict[str, dict[str, str]] = {
    "es": {
        "help_settings_button": (
            "Abre la ventana de Ajustes: radio, audio, spots, red, interfaz y plugins."
        ),
        "help_web_button": (
            "Activa/desactiva el servidor web remoto para controlar la consola "
            "desde el navegador."
        ),
        "help_mem_button": (
            "Abre las memorias de frecuencia: guarda, recupera y borra canales favoritos."
        ),
        "help_owrx_button": "Abre/cierra el visor de cascada de OpenWebRX+.",
        "help_digi_button": (
            "Abre/cierra la ventana de modos digitales (FT8 y similares) de OpenWebRX+."
        ),
        "help_spots_button": (
            "Abre el menú de spots: qué avisos de actividad mostrar en la cascada "
            "(CW, digitales, fonía, fuera de banda)."
        ),
        "help_edit_check": (
            "Modo edición de diseño: arrastra los controles con el botón derecho "
            "para recolocarlos; se guardan al desactivarlo."
        ),
        "help_ptt_button": (
            "Pulsa para transmitir (PTT). Se pone en rojo y muestra 'TX' mientras "
            "se transmite."
        ),
        "help_tune_button": (
            "Emite un tono de prueba mientras esté activado, útil para ajustar el "
            "ROE de la antena."
        ),
        "help_anr_check": "Activa/desactiva la reducción automática de ruido (ANR) en la recepción.",
        "help_anr_intensity": "Intensidad del ANR, de 1 (suave) a 10 (más agresivo).",
        "help_mode_selector": "Modo de recepción/transmisión: AM, FM, USB, LSB o CW.",
        "help_band_selector": "Selecciona la banda de frecuencias.",
        "help_channel_buttons": "Sube o baja de canal según el paso seleccionado.",
        "help_step_selector": "Paso de sintonía en kHz al mover el dial o cambiar de canal.",
        "help_frequency_entry": (
            "Frecuencia sintonizada (MHz.kHz,Hz). Haz clic y escribe para "
            "sintonizar directamente."
        ),
        "help_volume_dial": "Volumen del altavoz (audio recibido).",
        "help_gain_dial": "Ganancia del micrófono (audio transmitido).",
        "help_rx_source": (
            "Fuente del audio de recepción: 'Radio' (la propia radio) o 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Macro de autollamada {n}. Pulsa para reproducirla; se configura en "
            "Ajustes → Autollamada."
        ),
        "help_smeter": (
            "Medidor de señal (S-metro), calculado a partir del nivel reportado "
            "por OpenWebRX+."
        ),
    },
    "en": {
        "help_settings_button": (
            "Opens the Settings window: radio, audio, spots, network, interface and plugins."
        ),
        "help_web_button": (
            "Turns the remote web server on/off to control the console from a browser."
        ),
        "help_mem_button": (
            "Opens the frequency memories: save, recall and delete favourite channels."
        ),
        "help_owrx_button": "Opens/closes the OpenWebRX+ waterfall viewer.",
        "help_digi_button": (
            "Opens/closes the digital modes window (FT8 and similar) from OpenWebRX+."
        ),
        "help_spots_button": (
            "Opens the spots menu: which activity alerts to show on the waterfall "
            "(CW, digital, voice, out of band)."
        ),
        "help_edit_check": (
            "Layout edit mode: drag controls with the right mouse button to "
            "reposition them; saved when turned off."
        ),
        "help_ptt_button": (
            "Press to transmit (PTT). Turns red and shows 'TX' while transmitting."
        ),
        "help_tune_button": (
            "Emits a test tone while enabled, useful for tuning the antenna SWR."
        ),
        "help_anr_check": "Turns automatic noise reduction (ANR) on receive on/off.",
        "help_anr_intensity": "ANR intensity, from 1 (mild) to 10 (most aggressive).",
        "help_mode_selector": "Receive/transmit mode: AM, FM, USB, LSB or CW.",
        "help_band_selector": "Selects the frequency band.",
        "help_channel_buttons": "Moves up or down a channel by the selected step.",
        "help_step_selector": "Tuning step in kHz when turning the dial or changing channel.",
        "help_frequency_entry": (
            "Tuned frequency (MHz.kHz,Hz). Click and type to tune directly."
        ),
        "help_volume_dial": "Speaker volume (received audio).",
        "help_gain_dial": "Microphone gain (transmitted audio).",
        "help_rx_source": (
            "Receive audio source: 'Radio' (the radio itself) or 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Auto-call macro {n}. Click to play it; configured in Settings → Auto-call."
        ),
        "help_smeter": (
            "Signal meter (S-meter), computed from the level reported by OpenWebRX+."
        ),
    },
    "fr": {
        "help_settings_button": (
            "Ouvre la fenêtre Paramètres : radio, audio, spots, réseau, interface "
            "et extensions."
        ),
        "help_web_button": (
            "Active/désactive le serveur web distant pour piloter la console "
            "depuis un navigateur."
        ),
        "help_mem_button": (
            "Ouvre les mémoires de fréquence : enregistrer, rappeler et supprimer "
            "des canaux favoris."
        ),
        "help_owrx_button": "Ouvre/ferme la cascade d'OpenWebRX+.",
        "help_digi_button": (
            "Ouvre/ferme la fenêtre des modes numériques (FT8 et similaires) d'OpenWebRX+."
        ),
        "help_spots_button": (
            "Ouvre le menu des spots : quelles alertes d'activité afficher sur la "
            "cascade (CW, numérique, phonie, hors bande)."
        ),
        "help_edit_check": (
            "Mode édition de la disposition : glissez les contrôles avec le "
            "bouton droit pour les repositionner ; enregistré à la désactivation."
        ),
        "help_ptt_button": (
            "Appuyez pour émettre (PTT). Devient rouge et affiche « TX » pendant l'émission."
        ),
        "help_tune_button": (
            "Émet une tonalité de test tant que c'est activé, utile pour régler "
            "le ROS de l'antenne."
        ),
        "help_anr_check": "Active/désactive la réduction automatique de bruit (ANR) en réception.",
        "help_anr_intensity": "Intensité de l'ANR, de 1 (léger) à 10 (le plus agressif).",
        "help_mode_selector": "Mode de réception/émission : AM, FM, USB, LSB ou CW.",
        "help_band_selector": "Sélectionne la bande de fréquences.",
        "help_channel_buttons": "Monte ou descend d'un canal selon le pas sélectionné.",
        "help_step_selector": (
            "Pas de syntonisation en kHz lors de la rotation du cadran ou du "
            "changement de canal."
        ),
        "help_frequency_entry": (
            "Fréquence syntonisée (MHz.kHz,Hz). Cliquez et saisissez pour "
            "syntoniser directement."
        ),
        "help_volume_dial": "Volume du haut-parleur (audio reçu).",
        "help_gain_dial": "Gain du microphone (audio émis).",
        "help_rx_source": (
            "Source de l'audio de réception : « Radio » (la radio elle-même) ou "
            "« SDR » (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Macro d'appel automatique {n}. Cliquez pour la lancer ; se configure "
            "dans Paramètres → Appel auto."
        ),
        "help_smeter": (
            "S-mètre (indicateur de signal), calculé à partir du niveau rapporté "
            "par OpenWebRX+."
        ),
    },
    "de": {
        "help_settings_button": (
            "Öffnet das Einstellungsfenster: Funkgerät, Audio, Spots, Netzwerk, "
            "Oberfläche und Plugins."
        ),
        "help_web_button": (
            "Schaltet den entfernten Webserver ein/aus, um die Konsole per "
            "Browser zu steuern."
        ),
        "help_mem_button": (
            "Öffnet die Frequenzspeicher: Lieblingskanäle speichern, abrufen und löschen."
        ),
        "help_owrx_button": "Öffnet/schließt den Wasserfall-Viewer von OpenWebRX+.",
        "help_digi_button": (
            "Öffnet/schließt das Fenster für digitale Betriebsarten (FT8 u. Ä.) von OpenWebRX+."
        ),
        "help_spots_button": (
            "Öffnet das Spots-Menü: welche Aktivitätsmeldungen im Wasserfall "
            "angezeigt werden (CW, Digital, Sprechfunk, außerhalb des Bandes)."
        ),
        "help_edit_check": (
            "Layout-Bearbeitungsmodus: Bedienelemente mit der rechten Maustaste "
            "ziehen, um sie neu zu platzieren; wird beim Deaktivieren gespeichert."
        ),
        "help_ptt_button": (
            "Drücken zum Senden (PTT). Wird rot und zeigt 'TX' während der Sendung."
        ),
        "help_tune_button": (
            "Gibt einen Testton aus, solange aktiv; nützlich zum Abgleich des "
            "Antennen-SWR."
        ),
        "help_anr_check": "Schaltet die automatische Rauschunterdrückung (ANR) beim Empfang ein/aus.",
        "help_anr_intensity": "ANR-Intensität, von 1 (sanft) bis 10 (am aggressivsten).",
        "help_mode_selector": "Empfangs-/Sendebetriebsart: AM, FM, USB, LSB oder CW.",
        "help_band_selector": "Wählt das Frequenzband aus.",
        "help_channel_buttons": "Wechselt je nach gewählter Schrittweite einen Kanal nach oben oder unten.",
        "help_step_selector": "Abstimmschrittweite in kHz beim Drehen des Reglers oder Kanalwechsel.",
        "help_frequency_entry": (
            "Abgestimmte Frequenz (MHz.kHz,Hz). Anklicken und eingeben, um "
            "direkt abzustimmen."
        ),
        "help_volume_dial": "Lautsprecherlautstärke (empfangenes Audio).",
        "help_gain_dial": "Mikrofonverstärkung (gesendetes Audio).",
        "help_rx_source": (
            "Empfangs-Audioquelle: 'Radio' (das Funkgerät selbst) oder 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Anrufmakro {n}. Anklicken zum Abspielen; wird unter Einstellungen → "
            "Anrufmakro konfiguriert."
        ),
        "help_smeter": (
            "S-Meter (Signalanzeige), berechnet aus dem von OpenWebRX+ gemeldeten Pegel."
        ),
    },
    "it": {
        "help_settings_button": (
            "Apre la finestra Impostazioni: radio, audio, spot, rete, interfaccia e plugin."
        ),
        "help_web_button": (
            "Attiva/disattiva il server web remoto per controllare la console dal browser."
        ),
        "help_mem_button": (
            "Apre le memorie di frequenza: salva, richiama ed elimina i canali preferiti."
        ),
        "help_owrx_button": "Apre/chiude il visualizzatore a cascata di OpenWebRX+.",
        "help_digi_button": (
            "Apre/chiude la finestra dei modi digitali (FT8 e simili) di OpenWebRX+."
        ),
        "help_spots_button": (
            "Apre il menu degli spot: quali avvisi di attività mostrare sulla "
            "cascata (CW, digitali, fonia, fuori banda)."
        ),
        "help_edit_check": (
            "Modalità modifica del layout: trascina i controlli con il tasto "
            "destro per riposizionarli; si salva alla disattivazione."
        ),
        "help_ptt_button": (
            "Premi per trasmettere (PTT). Diventa rosso e mostra 'TX' durante la trasmissione."
        ),
        "help_tune_button": (
            "Emette un tono di prova finché è attivo, utile per regolare il ROS "
            "dell'antenna."
        ),
        "help_anr_check": "Attiva/disattiva la riduzione automatica del rumore (ANR) in ricezione.",
        "help_anr_intensity": "Intensità dell'ANR, da 1 (leggero) a 10 (più aggressivo).",
        "help_mode_selector": "Modo di ricezione/trasmissione: AM, FM, USB, LSB o CW.",
        "help_band_selector": "Seleziona la banda di frequenza.",
        "help_channel_buttons": "Sale o scende di canale in base al passo selezionato.",
        "help_step_selector": (
            "Passo di sintonia in kHz quando si ruota la manopola o si cambia canale."
        ),
        "help_frequency_entry": (
            "Frequenza sintonizzata (MHz.kHz,Hz). Clicca e digita per sintonizzare direttamente."
        ),
        "help_volume_dial": "Volume dell'altoparlante (audio ricevuto).",
        "help_gain_dial": "Guadagno del microfono (audio trasmesso).",
        "help_rx_source": (
            "Sorgente dell'audio di ricezione: 'Radio' (la radio stessa) o 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Macro di chiamata automatica {n}. Clicca per riprodurla; si "
            "configura in Impostazioni → Chiamata automatica."
        ),
        "help_smeter": (
            "S-metro (misuratore di segnale), calcolato dal livello riportato da OpenWebRX+."
        ),
    },
    "pt": {
        "help_settings_button": (
            "Abre a janela de Configurações: rádio, áudio, spots, rede, "
            "interface e plugins."
        ),
        "help_web_button": (
            "Ativa/desativa o servidor web remoto para controlar a consola a "
            "partir do navegador."
        ),
        "help_mem_button": (
            "Abre as memórias de frequência: guardar, recuperar e apagar canais favoritos."
        ),
        "help_owrx_button": "Abre/fecha o visualizador em cascata do OpenWebRX+.",
        "help_digi_button": (
            "Abre/fecha a janela dos modos digitais (FT8 e semelhantes) do OpenWebRX+."
        ),
        "help_spots_button": (
            "Abre o menu de spots: que avisos de atividade mostrar na cascata "
            "(CW, digitais, fonia, fora de banda)."
        ),
        "help_edit_check": (
            "Modo de edição do layout: arraste os controlos com o botão direito "
            "para os reposicionar; é guardado ao desativar."
        ),
        "help_ptt_button": (
            "Prima para transmitir (PTT). Fica vermelho e mostra 'TX' durante a transmissão."
        ),
        "help_tune_button": (
            "Emite um tom de teste enquanto ativo, útil para ajustar o ROE da antena."
        ),
        "help_anr_check": "Ativa/desativa a redução automática de ruído (ANR) na receção.",
        "help_anr_intensity": "Intensidade do ANR, de 1 (suave) a 10 (mais agressivo).",
        "help_mode_selector": "Modo de receção/transmissão: AM, FM, USB, LSB ou CW.",
        "help_band_selector": "Seleciona a banda de frequência.",
        "help_channel_buttons": "Sobe ou desce de canal conforme o passo selecionado.",
        "help_step_selector": "Passo de sintonia em kHz ao rodar o dial ou mudar de canal.",
        "help_frequency_entry": (
            "Frequência sintonizada (MHz.kHz,Hz). Clique e escreva para sintonizar diretamente."
        ),
        "help_volume_dial": "Volume do altifalante (áudio recebido).",
        "help_gain_dial": "Ganho do microfone (áudio transmitido).",
        "help_rx_source": (
            "Fonte do áudio de receção: 'Radio' (o próprio rádio) ou 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Macro de chamada automática {n}. Clique para a reproduzir; "
            "configura-se em Configurações → Chamada automática."
        ),
        "help_smeter": (
            "Medidor de sinal (S-metro), calculado a partir do nível reportado pelo OpenWebRX+."
        ),
    },
    "tr": {
        "help_settings_button": (
            "Ayarlar penceresini açar: radyo, ses, spotlar, ağ, arayüz ve eklentiler."
        ),
        "help_web_button": (
            "Konsolu tarayıcıdan kontrol etmek için uzak web sunucusunu açar/kapatır."
        ),
        "help_mem_button": "Frekans hafızalarını açar: favori kanalları kaydet, çağır ve sil.",
        "help_owrx_button": "OpenWebRX+ şelale görüntüleyicisini açar/kapatır.",
        "help_digi_button": "OpenWebRX+'in dijital mod penceresini (FT8 ve benzerleri) açar/kapatır.",
        "help_spots_button": (
            "Spot menüsünü açar: şelalede hangi etkinlik uyarılarının "
            "gösterileceği (CW, dijital, sesli, bant dışı)."
        ),
        "help_edit_check": (
            "Düzen düzenleme modu: kontrolleri sağ tuşla sürükleyerek yeniden "
            "konumlandırın; kapatınca kaydedilir."
        ),
        "help_ptt_button": (
            "Yayın yapmak için basın (PTT). Yayın sırasında kırmızıya döner ve "
            "'TX' gösterir."
        ),
        "help_tune_button": "Etkinken bir test tonu yayar; anten SWR ayarı için kullanışlıdır.",
        "help_anr_check": "Alımda otomatik gürültü azaltmayı (ANR) açar/kapatır.",
        "help_anr_intensity": "ANR yoğunluğu, 1 (hafif) ile 10 (en agresif) arası.",
        "help_mode_selector": "Alım/gönderim modu: AM, FM, USB, LSB veya CW.",
        "help_band_selector": "Frekans bandını seçer.",
        "help_channel_buttons": "Seçilen adıma göre kanalı yukarı veya aşağı taşır.",
        "help_step_selector": "Kadranı çevirirken veya kanal değiştirirken kHz cinsinden ayar adımı.",
        "help_frequency_entry": (
            "Ayarlanan frekans (MHz.kHz,Hz). Doğrudan ayarlamak için tıklayıp yazın."
        ),
        "help_volume_dial": "Hoparlör ses düzeyi (alınan ses).",
        "help_gain_dial": "Mikrofon kazancı (gönderilen ses).",
        "help_rx_source": (
            "Alım ses kaynağı: 'Radio' (radyonun kendisi) veya 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Otomatik çağrı makrosu {n}. Çalmak için tıklayın; Ayarlar → "
            "Otomatik çağrı'da yapılandırılır."
        ),
        "help_smeter": "S-metre (sinyal göstergesi), OpenWebRX+ tarafından bildirilen seviyeden hesaplanır.",
    },
    "pl": {
        "help_settings_button": "Otwiera okno Ustawień: radio, dźwięk, spoty, sieć, interfejs i wtyczki.",
        "help_web_button": (
            "Włącza/wyłącza zdalny serwer WWW do sterowania konsolą z przeglądarki."
        ),
        "help_mem_button": (
            "Otwiera pamięci częstotliwości: zapisuj, przywołuj i usuwaj ulubione kanały."
        ),
        "help_owrx_button": "Otwiera/zamyka podgląd kaskady OpenWebRX+.",
        "help_digi_button": "Otwiera/zamyka okno trybów cyfrowych (FT8 i podobnych) OpenWebRX+.",
        "help_spots_button": (
            "Otwiera menu spotów: jakie alerty aktywności pokazywać na kaskadzie "
            "(CW, cyfrowe, fonia, poza pasmem)."
        ),
        "help_edit_check": (
            "Tryb edycji układu: przeciągaj elementy prawym przyciskiem myszy, "
            "aby je przemieścić; zapisywane po wyłączeniu."
        ),
        "help_ptt_button": (
            "Naciśnij, aby nadawać (PTT). Zmienia kolor na czerwony i pokazuje "
            "'TX' podczas nadawania."
        ),
        "help_tune_button": "Emituje ton testowy, gdy jest włączony; przydatny do strojenia SWR anteny.",
        "help_anr_check": "Włącza/wyłącza automatyczną redukcję szumów (ANR) przy odbiorze.",
        "help_anr_intensity": "Intensywność ANR, od 1 (łagodna) do 10 (najbardziej agresywna).",
        "help_mode_selector": "Tryb odbioru/nadawania: AM, FM, USB, LSB lub CW.",
        "help_band_selector": "Wybiera pasmo częstotliwości.",
        "help_channel_buttons": "Przesuwa kanał w górę lub w dół o wybrany krok.",
        "help_step_selector": "Krok strojenia w kHz przy obracaniu pokrętła lub zmianie kanału.",
        "help_frequency_entry": (
            "Nastrojona częstotliwość (MHz.kHz,Hz). Kliknij i wpisz, aby "
            "nastroić bezpośrednio."
        ),
        "help_volume_dial": "Głośność głośnika (odebrany dźwięk).",
        "help_gain_dial": "Wzmocnienie mikrofonu (nadawany dźwięk).",
        "help_rx_source": (
            "Źródło dźwięku odbioru: 'Radio' (samo radio) lub 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Makro automatycznego wywołania {n}. Kliknij, aby je odtworzyć; "
            "konfigurowane w Ustawieniach → Autowywołanie."
        ),
        "help_smeter": "S-metr (miernik sygnału), obliczany na podstawie poziomu zgłaszanego przez OpenWebRX+.",
    },
    "ru": {
        "help_settings_button": "Открывает окно настроек: радио, звук, споты, сеть, интерфейс и плагины.",
        "help_web_button": (
            "Включает/выключает удалённый веб-сервер для управления консолью из браузера."
        ),
        "help_mem_button": (
            "Открывает частотную память: сохранение, вызов и удаление избранных каналов."
        ),
        "help_owrx_button": "Открывает/закрывает окно водопада OpenWebRX+.",
        "help_digi_button": (
            "Открывает/закрывает окно цифровых видов связи (FT8 и подобных) OpenWebRX+."
        ),
        "help_spots_button": (
            "Открывает меню спотов: какие оповещения об активности показывать "
            "на водопаде (CW, цифровые, телефония, вне диапазона)."
        ),
        "help_edit_check": (
            "Режим редактирования расположения: перетаскивайте элементы правой "
            "кнопкой мыши; сохраняется при выключении."
        ),
        "help_ptt_button": (
            "Нажмите для передачи (PTT). Становится красной и показывает 'TX' "
            "во время передачи."
        ),
        "help_tune_button": "Издаёт тестовый тон, пока включено; полезно для настройки КСВ антенны.",
        "help_anr_check": "Включает/выключает автоматическое шумоподавление (ANR) при приёме.",
        "help_anr_intensity": "Интенсивность ANR, от 1 (слабая) до 10 (самая сильная).",
        "help_mode_selector": "Режим приёма/передачи: AM, FM, USB, LSB или CW.",
        "help_band_selector": "Выбирает диапазон частот.",
        "help_channel_buttons": "Переключает канал вверх или вниз с выбранным шагом.",
        "help_step_selector": "Шаг настройки в кГц при вращении ручки или смене канала.",
        "help_frequency_entry": (
            "Настроенная частота (МГц.кГц,Гц). Нажмите и введите значение для "
            "прямой настройки."
        ),
        "help_volume_dial": "Громкость динамика (принимаемый звук).",
        "help_gain_dial": "Усиление микрофона (передаваемый звук).",
        "help_rx_source": (
            "Источник звука приёма: 'Radio' (само радио) или 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Макрос автовызова {n}. Нажмите для воспроизведения; настраивается "
            "в Настройки → Автовызов."
        ),
        "help_smeter": "S-метр (индикатор сигнала), рассчитываемый по уровню, сообщаемому OpenWebRX+.",
    },
    "gl": {
        "help_settings_button": "Abre a xanela de Axustes: radio, audio, spots, rede, interface e plugins.",
        "help_web_button": (
            "Activa/desactiva o servidor web remoto para controlar a consola "
            "desde o navegador."
        ),
        "help_mem_button": (
            "Abre as memorias de frecuencia: garda, recupera e elimina canles favoritas."
        ),
        "help_owrx_button": "Abre/pecha o visor en fervenza de OpenWebRX+.",
        "help_digi_button": "Abre/pecha a xanela dos modos dixitais (FT8 e similares) de OpenWebRX+.",
        "help_spots_button": (
            "Abre o menú de spots: que avisos de actividade amosar na fervenza "
            "(CW, dixitais, fonía, fóra de banda)."
        ),
        "help_edit_check": (
            "Modo de edición do deseño: arrastra os controis co botón dereito "
            "para recolocalos; gárdase ao desactivalo."
        ),
        "help_ptt_button": (
            "Preme para transmitir (PTT). Ponse en vermello e mostra 'TX' mentres transmite."
        ),
        "help_tune_button": (
            "Emite un ton de proba mentres estea activado, útil para axustar o "
            "ROE da antena."
        ),
        "help_anr_check": "Activa/desactiva a redución automática de ruído (ANR) na recepción.",
        "help_anr_intensity": "Intensidade do ANR, de 1 (suave) a 10 (máis agresivo).",
        "help_mode_selector": "Modo de recepción/transmisión: AM, FM, USB, LSB ou CW.",
        "help_band_selector": "Selecciona a banda de frecuencias.",
        "help_channel_buttons": "Sobe ou baixa de canle segundo o paso seleccionado.",
        "help_step_selector": "Paso de sintonía en kHz ao mover o dial ou cambiar de canle.",
        "help_frequency_entry": (
            "Frecuencia sintonizada (MHz.kHz,Hz). Fai clic e escribe para sintonizar directamente."
        ),
        "help_volume_dial": "Volume do altofalante (audio recibido).",
        "help_gain_dial": "Ganancia do micrófono (audio transmitido).",
        "help_rx_source": (
            "Fonte do audio de recepción: 'Radio' (a propia radio) ou 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Macro de autochamada {n}. Preme para reproducila; configúrase en "
            "Axustes → Autochamada."
        ),
        "help_smeter": "Medidor de sinal (S-metro), calculado a partir do nivel indicado por OpenWebRX+.",
    },
    "ca": {
        "help_settings_button": (
            "Obre la finestra de Configuració: ràdio, àudio, spots, xarxa, "
            "interfície i connectors."
        ),
        "help_web_button": (
            "Activa/desactiva el servidor web remot per controlar la consola "
            "des del navegador."
        ),
        "help_mem_button": (
            "Obre les memòries de freqüència: desa, recupera i elimina canals preferits."
        ),
        "help_owrx_button": "Obre/tanca el visor en cascada d'OpenWebRX+.",
        "help_digi_button": "Obre/tanca la finestra dels modes digitals (FT8 i similars) d'OpenWebRX+.",
        "help_spots_button": (
            "Obre el menú d'spots: quins avisos d'activitat mostrar a la "
            "cascada (CW, digitals, fonia, fora de banda)."
        ),
        "help_edit_check": (
            "Mode d'edició del disseny: arrossega els controls amb el botó dret "
            "per recol·locar-los; es desa en desactivar-lo."
        ),
        "help_ptt_button": (
            "Prem per transmetre (PTT). Es torna vermell i mostra 'TX' mentre transmet."
        ),
        "help_tune_button": (
            "Emet un to de prova mentre estigui activat, útil per ajustar el "
            "ROE de l'antena."
        ),
        "help_anr_check": "Activa/desactiva la reducció automàtica de soroll (ANR) en recepció.",
        "help_anr_intensity": "Intensitat de l'ANR, d'1 (suau) a 10 (més agressiu).",
        "help_mode_selector": "Mode de recepció/transmissió: AM, FM, USB, LSB o CW.",
        "help_band_selector": "Selecciona la banda de freqüències.",
        "help_channel_buttons": "Puja o baixa de canal segons el pas seleccionat.",
        "help_step_selector": "Pas de sintonia en kHz en moure el dial o canviar de canal.",
        "help_frequency_entry": (
            "Freqüència sintonitzada (MHz.kHz,Hz). Fes clic i escriu per sintonitzar directament."
        ),
        "help_volume_dial": "Volum de l'altaveu (àudio rebut).",
        "help_gain_dial": "Guany del micròfon (àudio transmès).",
        "help_rx_source": (
            "Font de l'àudio de recepció: 'Radio' (la ràdio mateixa) o 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "Macro de trucada automàtica {n}. Fes clic per reproduir-la; es "
            "configura a Configuració → Trucada automàtica."
        ),
        "help_smeter": "Mesurador de senyal (S-metre), calculat a partir del nivell indicat per OpenWebRX+.",
    },
    "eu": {
        "help_settings_button": (
            "Ezarpenak lehioa irekitzen du: irratia, audioa, spotak, sarea, "
            "interfazea eta pluginak."
        ),
        "help_web_button": (
            "Urruneko web zerbitzaria aktibatu/desaktibatzen du kontsola "
            "nabigatzailetik kontrolatzeko."
        ),
        "help_mem_button": (
            "Maiztasun-memoriak irekitzen ditu: gorde, berreskuratu eta ezabatu "
            "gogoko kanalak."
        ),
        "help_owrx_button": "OpenWebRX+ren ur-jauzi ikustailea irekitzen/isten du.",
        "help_digi_button": (
            "OpenWebRX+ren modu digitalen leihoa (FT8 eta antzekoak) irekitzen/isten du."
        ),
        "help_spots_button": (
            "Spot-menua irekitzen du: zein jarduera-abisu erakutsi ur-jauzian "
            "(CW, digitalak, ahotsezkoa, bandaz kanpo)."
        ),
        "help_edit_check": (
            "Diseinua editatzeko modua: arrastatu kontrolak eskuineko "
            "botoiarekin birkokatzeko; desaktibatzean gordetzen da."
        ),
        "help_ptt_button": (
            "Sakatu transmititzeko (PTT). Gorri jartzen da eta 'TX' erakusten "
            "du transmititzen ari denean."
        ),
        "help_tune_button": (
            "Proba-tonu bat igortzen du aktibatuta dagoen bitartean; antenaren "
            "SWR doitzeko erabilgarria."
        ),
        "help_anr_check": "Harreran zarataren murrizketa automatikoa (ANR) aktibatu/desaktibatzen du.",
        "help_anr_intensity": "ANR-aren intentsitatea, 1etik (arina) 10era (agresiboena).",
        "help_mode_selector": "Harrera/igorpen modua: AM, FM, USB, LSB edo CW.",
        "help_band_selector": "Maiztasun-banda hautatzen du.",
        "help_channel_buttons": "Kanala gora edo behera aldatzen du hautatutako urratsaren arabera.",
        "help_step_selector": "Sintonizazio-urratsa kHz-tan, diala biratzean edo kanala aldatzean.",
        "help_frequency_entry": (
            "Sintonizatutako maiztasuna (MHz.kHz,Hz). Egin klik eta idatzi "
            "zuzenean sintonizatzeko."
        ),
        "help_volume_dial": "Bozgorailuaren bolumena (jasotako audioa).",
        "help_gain_dial": "Mikrofonoaren irabazia (igorritako audioa).",
        "help_rx_source": (
            "Harrera-audioaren iturria: 'Radio' (irratia bera) edo 'SDR' (OpenWebRX+)."
        ),
        "help_autocall_slot": (
            "{n}. autodei-makroa. Klik egin erreproduzitzeko; Ezarpenak → "
            "Autodeia atalean konfiguratzen da."
        ),
        "help_smeter": "S-metroa (seinale-neurgailua), OpenWebRX+k jakinarazitako mailatik kalkulatua.",
    },
}


def console_help(key: str, lang: str = DEFAULT_LANG, **kwargs: object) -> str:
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


__all__ = ["DEFAULT_LANG", "HELP", "console_help"]
